// Bedside temperature/humidity sensor: Adafruit QT Py ESP32 Pico + SHT41 (STEMMA QT).
//
// Radio rule: Wi-Fi is OFF from 21:30 to 07:30. Readings every 30 s go into RAM;
// after 07:30 the board turns Wi-Fi on once, re-syncs its clock, POSTs each finished
// night to the receiver on your computer (receiver/bedside_receiver.py), and turns Wi-Fi off
// again. It stays awake (USB powered) so its clock runs on the accurate crystal rather than
// the sleep timer. The one exception: right after power-up it connects once to learn the time.
//
// Finding the receiver: by name over mDNS (RECEIVER_HOST.local), then the fixed address in
// device_config.h if you set one (RECEIVER_IP), then the last address that accepted an upload
// (kept in flash). Every power-up leaves a line in the receiver's log
// (GET /bedside/hello?...), so you can see restarts and their cause without going to the bed.
// A watchdog restarts a hung board. A day with nothing to upload still gets one morning
// check-in, so a sensor that stopped answering (a loose cable) can't look the same as a board
// that's off.
//
// Settings live in device_config.h (gitignored), written by ./make_device_config.sh.

#include <ESPmDNS.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "Adafruit_SHT4x.h"
#include "device_config.h"
#include "logic.h"

#ifndef TZ_INFO
#error "device_config.h has no TZ_INFO: run ./make_device_config.sh again"
#endif
#ifndef RECEIVER_PORT
#define RECEIVER_PORT 7690
#endif

using namespace bedside;

static const uint32_t SAMPLE_MS = 30UL * 1000;
static const uint32_t RETRY_MS = 60UL * 60 * 1000;          // failed upload / time sync
static const uint32_t WIFI_TIMEOUT_MS = 20UL * 1000;
static const uint32_t WATCHDOG_MS = 180UL * 1000;           // longer than any one blocking step
static const uint32_t CHECK_IN_MS = 23UL * 60 * 60 * 1000;  // at most one empty-handed contact a day
static const int MDNS_TRIES = 3;
static const uint32_t MDNS_TRY_MS = 2000;
static const char* FIRMWARE_ID = "1.0.0";

Adafruit_SHT4x sht4;
ReadingBuffer<4000> readings;  // ~3.3 nights at 30 s; oldest dropped beyond that
bool sensorOk = false;
bool timeValid = false;
uint32_t lastSampleMs = 0;
uint32_t nextNetAttemptMs = 0;
Preferences prefs;
uint32_t configuredReceiver = 0;  // RECEIVER_IP from device_config.h; 0 = not set
uint32_t lastGoodReceiver = 0;    // network-order IPv4 from flash; 0 = none yet
int failedAttempts = 0;           // upload attempts since the last success
int lastHttpCode = 0;             // last upload result; 0 = none, -1 = no route, -2 = no Wi-Fi
int readFailures = 0;             // sensor reads that failed since the last note to the receiver
uint32_t lastContactMs = 0;       // last time the radio came on outside power-up

static bool wifiOn() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) delay(250);
    return WiFi.status() == WL_CONNECTED;
}

static void wifiOff() {
    MDNS.end();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
}

static bool syncClock() {
    configTzTime(TZ_INFO, "pool.ntp.org", "time.google.com");
    struct tm t;
    for (int i = 0; i < 20; i++) {
        if (getLocalTime(&t, 500) && t.tm_year + 1900 >= 2026) return true;
    }
    return false;
}

static int minuteOfDay(time_t epoch) {
    struct tm lt;
    localtime_r(&epoch, &lt);
    return lt.tm_hour * 60 + lt.tm_min;
}

// "YYYY-MM-DD" of the evening this reading's night started on.
static void nightOf(time_t epoch, char* out, size_t cap) {
    time_t shifted = belongsToPreviousDate(minuteOfDay(epoch)) ? epoch - 86400 : epoch;
    struct tm lt;
    localtime_r(&shifted, &lt);
    strftime(out, cap, "%Y-%m-%d", &lt);
}

static uint32_t parseConfiguredReceiver() {
#ifdef RECEIVER_IP
    IPAddress ip;
    if (ip.fromString(RECEIVER_IP)) return (uint32_t)ip;
    Serial.printf("RECEIVER_IP \"%s\" is not an IPv4 address; ignoring it\n", RECEIVER_IP);
#endif
    return 0;
}

// Asks by name a few times: the first query after Wi-Fi comes up can go unanswered.
static uint32_t lookupReceiverByName() {
    if (!MDNS.begin("bedside-sensor")) {
        Serial.println("mDNS would not start");
        return 0;
    }
    for (int i = 0; i < MDNS_TRIES; i++) {
        IPAddress ip = MDNS.queryHost(RECEIVER_HOST, MDNS_TRY_MS);
        if (ip != IPAddress(0, 0, 0, 0)) return (uint32_t)ip;
        delay(500);
    }
    Serial.printf("mDNS found no %s.local\n", RECEIVER_HOST);
    return 0;
}

// 0 means no route, and the caller doesn't try: a failure a person can read on serial,
// never a POST into a stale address.
static uint32_t receiverAddress() {
    uint32_t ip = pickReceiver(lookupReceiverByName(), lastGoodReceiver, configuredReceiver);
    Serial.printf("receiver: %s (last good %s)\n", IPAddress(ip).toString().c_str(),
                  IPAddress(lastGoodReceiver).toString().c_str());
    return ip;
}

static void rememberReceiver(uint32_t ip) {
    if (!shouldRemember(ip, lastGoodReceiver)) return;  // flash only when it changes
    lastGoodReceiver = ip;
    prefs.putUInt("receiver", ip);
}

// One log line on the receiver, no token and no data.
static void sayHello(uint32_t receiver) {
    if (receiver == 0) return;
    char path[140];
    formatHello(path, sizeof path, FIRMWARE_ID, (int)esp_reset_reason(), readings.size(), failedAttempts,
                lastHttpCode, WiFi.RSSI(), readFailures);
    HTTPClient http;
    http.setConnectTimeout(3000);
    http.begin(String("http://") + IPAddress(receiver).toString() + ":" + RECEIVER_PORT + path);
    int code = http.GET();
    http.end();
    Serial.printf("hello %s: HTTP %d\n", path, code);
    if (code > 0) {
        rememberReceiver(receiver);  // it answered, so a later mDNS miss has a route
        readFailures = 0;
    }
}

// Sends every complete night in the buffer, oldest first. Stops at the first failure.
static bool uploadNights() {
    uint32_t receiver = receiverAddress();
    if (receiver == 0) {
        lastHttpCode = -1;
        return false;
    }
    IPAddress ip(receiver);
    while (readings.size() > 0) {
        esp_task_wdt_reset();
        char night[11], other[11];
        nightOf(readings.at(0).epoch, night, sizeof night);
        int n = 0;
        while (n < readings.size()) {
            nightOf(readings.at(n).epoch, other, sizeof other);
            if (strcmp(night, other) != 0) break;
            n++;
        }
        String body = CSV_HEADER;
        if (!body.reserve(n * 48 + 40)) {  // never post a truncated night and then drop it
            Serial.printf("no memory for night %s (%d rows)\n", night, n);
            lastHttpCode = -3;
            return false;
        }
        char row[80], stamp[24];
        for (int i = 0; i < n; i++) {
            time_t e = readings.at(i).epoch;
            struct tm lt;
            localtime_r(&e, &lt);
            strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%S", &lt);
            formatRow(row, sizeof row, stamp, readings.at(i));
            body += row;
        }
        HTTPClient http;
        http.begin(String("http://") + ip.toString() + ":" + RECEIVER_PORT + "/bedside/temp");
        http.addHeader("Content-Type", "text/csv");
        http.addHeader("X-Token", RECEIVER_TOKEN);
        http.addHeader("X-Night", night);
        int code = http.POST(body);
        http.end();
        Serial.printf("upload night %s (%d rows) to %s: HTTP %d\n", night, n, ip.toString().c_str(), code);
        lastHttpCode = code;
        if (code != 200) return false;
        rememberReceiver(receiver);
        readings.dropFront(n);
    }
    return true;
}

static bool startSensor() {
    if (!sht4.begin(&Wire1)) return false;
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
    return true;
}

static void takeReading() {
    if (!sensorOk) sensorOk = startSensor();  // a re-seated cable comes back on its own
    sensors_event_t humidity, temp;
    if (!sensorOk || !sht4.getEvent(&humidity, &temp)) {
        sensorOk = false;
        readFailures++;
        return;
    }
    readings.push({(uint32_t)time(nullptr), (int16_t)lroundf(temp.temperature * 100),
                   (uint16_t)lroundf(humidity.relative_humidity * 100)});
}

void setup() {
    Serial.begin(115200);
    const esp_task_wdt_config_t watchdog = {WATCHDOG_MS, 0, true};  // ms, no idle cores, restart
    if (esp_task_wdt_reconfigure(&watchdog) != ESP_OK) esp_task_wdt_init(&watchdog);
    esp_task_wdt_add(nullptr);
    prefs.begin("bedside", false);
    lastGoodReceiver = prefs.getUInt("receiver", 0);
    configuredReceiver = parseConfiguredReceiver();
    Wire1.begin(SDA1, SCL1);  // the STEMMA QT port is the second I2C bus on this board
    sensorOk = startSensor();
    Serial.printf("SHT41 %s\n", sensorOk ? "found" : "NOT FOUND");
    sensors_event_t rh, t;  // one reading at power-up so a person can check the sensor now
    if (sensorOk && sht4.getEvent(&rh, &t)) {
        Serial.printf("now %.2f C, %.1f %%RH\n", t.temperature, rh.relative_humidity);
    }
    // Power-up exception to the radio rule: one connection to learn the time.
    bool connected = wifiOn();
    Serial.printf("Wi-Fi %s\n", connected ? "connected" : "NOT connected (check name/password, 2.4 GHz)");
    timeValid = connected && syncClock();
    esp_task_wdt_reset();
    if (connected) sayHello(receiverAddress());
    wifiOff();
    if (!timeValid) nextNetAttemptMs = millis() + RETRY_MS;
    Serial.printf("clock %s\n", timeValid ? "synced" : "NOT synced (retrying hourly)");
}

void loop() {
    esp_task_wdt_reset();
    uint32_t now = millis();
    if (now - lastSampleMs >= SAMPLE_MS) {
        lastSampleMs = now;
        if (!timeValid) {
            if ((int32_t)(now - nextNetAttemptMs) >= 0) {
                timeValid = wifiOn() && syncClock();
                wifiOff();
                nextNetAttemptMs = now + RETRY_MS;
            }
        } else if (inWindow(minuteOfDay(time(nullptr)))) {
            takeReading();  // radio stays off all night
        } else if (readings.size() > 0 && (int32_t)(now - nextNetAttemptMs) >= 0) {
            bool connected = wifiOn();
            bool ok = connected && (syncClock(), uploadNights());
            if (!connected) lastHttpCode = -2;
            if (!ok) failedAttempts++;
            esp_task_wdt_reset();
            // Best effort: a failure, the first success after failures, or bad sensor reads.
            if (connected && (failedAttempts > 0 || readFailures > 0)) {
                sayHello(lastGoodReceiver != 0 ? lastGoodReceiver : configuredReceiver);
            }
            wifiOff();
            lastContactMs = now;
            Serial.printf("upload attempt %s; %d failed before this; last code %d; %d rows held\n",
                          ok ? "ok" : "FAILED", failedAttempts, lastHttpCode, readings.size());
            if (ok) failedAttempts = 0;
            nextNetAttemptMs = ok ? now : now + RETRY_MS;
        } else if (readings.size() == 0 && now - lastContactMs >= CHECK_IN_MS &&
                   (int32_t)(now - nextNetAttemptMs) >= 0) {
            // Nothing to send all night is itself news: say so once, by daylight.
            bool connected = wifiOn();
            if (connected) sayHello(receiverAddress());
            wifiOff();
            lastContactMs = now;
        }
    }
    delay(200);
}
