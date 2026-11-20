// Pure logic for the bedside temperature and humidity sensor. No Arduino types, so it also
// compiles on a computer for the unit tests (test_logic.cpp).
#pragma once

#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace bedside {

// The logging window, minutes after local midnight. Change both here and in test_logic.cpp.
constexpr int START_MIN = 21 * 60 + 30;  // 21:30
constexpr int END_MIN = 7 * 60 + 30;     // 07:30

// True between 21:30 (inclusive) and 07:30 (exclusive), across midnight.
inline bool inWindow(int minuteOfDay) { return minuteOfDay >= START_MIN || minuteOfDay < END_MIN; }

// Readings before 07:30 belong to the night that started the previous evening.
inline bool belongsToPreviousDate(int minuteOfDay) { return minuteOfDay < END_MIN; }

struct Reading {
    uint32_t epoch;     // UTC seconds
    int16_t centiC;     // temperature x 100
    uint16_t centiRH;   // relative humidity x 100
};

// Fixed-size FIFO. When full, the oldest reading is dropped so the newest
// nights survive a long upload outage.
template <int N>
class ReadingBuffer {
   public:
    int size() const { return count_; }
    const Reading& at(int i) const { return data_[(head_ + i) % N]; }

    void push(const Reading& r) {
        if (count_ == N) {
            head_ = (head_ + 1) % N;
            count_--;
        }
        data_[(head_ + count_) % N] = r;
        count_++;
    }

    void dropFront(int n) {
        if (n > count_) n = count_;
        head_ = (head_ + n) % N;
        count_ -= n;
    }

   private:
    Reading data_[N];
    int head_ = 0;
    int count_ = 0;
};

// Where to send the upload: the address found by name, else the fixed address from
// device_config.h (RECEIVER_IP, optional), else the last address that accepted an upload,
// else 0 (no route, so don't try). Addresses are IPv4 as uint32; 0 means none.
inline uint32_t pickReceiver(uint32_t foundByName, uint32_t lastGood, uint32_t configured = 0) {
    if (foundByName != 0) return foundByName;
    if (configured != 0) return configured;
    return lastGood;
}

// Write flash only when a working address changed.
inline bool shouldRemember(uint32_t worked, uint32_t lastGood) { return worked != 0 && worked != lastGood; }

// The path for a power-up or problem note. The receiver logs every request line, so a person
// or an agent can read the sensor's state there. Holds no token and no readings.
// Returns chars written.
inline int formatHello(char* out, size_t cap, const char* firmware, int resetReason, int rowsHeld,
                       int failedAttempts, int lastHttpCode, int rssi, int readFailures) {
    return snprintf(out, cap, "/bedside/hello?fw=%s&reset=%d&rows=%d&fails=%d&code=%d&rssi=%d&readfail=%d",
                    firmware, resetReason, rowsHeld, failedAttempts, lastHttpCode, rssi, readFailures);
}

constexpr const char* CSV_HEADER = "time_local,epoch,temp_c,rh_pct\n";

// One CSV row; timeLocal is "YYYY-MM-DDTHH:MM:SS". Returns chars written.
inline int formatRow(char* out, size_t cap, const char* timeLocal, const Reading& r) {
    int c = r.centiC;
    const char* sign = c < 0 ? "-" : "";
    if (c < 0) c = -c;
    return snprintf(out, cap, "%s,%lu,%s%d.%02d,%u.%02u\n", timeLocal, (unsigned long)r.epoch, sign, c / 100,
                    c % 100, (unsigned)(r.centiRH / 100), (unsigned)(r.centiRH % 100));
}

}  // namespace bedside
