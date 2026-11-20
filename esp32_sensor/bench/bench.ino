// Bench test for the bedside sensor: prints the SHT41 once a second, no Wi-Fi.
// Use it to check a new board, do the pinch test, or measure the board's heat bias.
//   ./firmware.sh bench    flash this, then show the readings (Ctrl-C to quit)
// Flash the real firmware afterwards with ./firmware.sh flash.

#include <Wire.h>

#include "Adafruit_SHT4x.h"

Adafruit_SHT4x sht4;
bool sensorOk = false;

static void scanBus() {
    Serial.print("I2C devices on the STEMMA QT port:");
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire1.beginTransmission(addr);
        if (Wire1.endTransmission() == 0) {
            Serial.printf(" 0x%02X", addr);
            found++;
        }
    }
    Serial.println(found ? "" : " none (check the cable)");
}

void setup() {
    Serial.begin(115200);
    delay(1500);  // give the Mac time to open the port after a reset
    Wire1.begin(SDA1, SCL1);  // the STEMMA QT port is the second I2C bus on this board
    Serial.println("bench test: SHT41 every 1 s");
    scanBus();  // the SHT41 answers at 0x44
    sensorOk = sht4.begin(&Wire1);
    if (sensorOk) {
        sht4.setPrecision(SHT4X_HIGH_PRECISION);
        sht4.setHeater(SHT4X_NO_HEATER);
        Serial.printf("SHT41 found, serial 0x%08lX\n", (unsigned long)sht4.readSerial());
    } else {
        Serial.println("SHT41 NOT FOUND");
    }
}

void loop() {
    static uint32_t n = 0;
    if (!sensorOk) {
        sensorOk = sht4.begin(&Wire1);
        if (!sensorOk) {
            Serial.println("SHT41 NOT FOUND, retrying");
            delay(2000);
            return;
        }
    }
    sensors_event_t rh, t;
    if (sht4.getEvent(&rh, &t)) {
        Serial.printf("%5lu s  %6.2f C  %6.2f F  %5.1f %%RH\n", (unsigned long)n,
                      t.temperature, t.temperature * 9 / 5 + 32, rh.relative_humidity);
    } else {
        Serial.println("read failed");
    }
    n++;
    delay(1000);
}
