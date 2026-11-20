// Host-side tests for logic.h. Run from the repo root:
//   c++ -std=c++17 esp32_sensor/test_logic.cpp -o /tmp/bedside_logic && /tmp/bedside_logic
// (./check.sh runs this for you.)
#include <cassert>
#include <cstdio>
#include <cstring>

#include "logic.h"

using namespace bedside;

static void test_window_is_2130_to_0730() {
    assert(inWindow(21 * 60 + 30));
    assert(inWindow(23 * 60 + 59));
    assert(inWindow(0));
    assert(inWindow(7 * 60 + 29));
    assert(!inWindow(7 * 60 + 30));
    assert(!inWindow(14 * 60));
    assert(!inWindow(21 * 60 + 29));
}

static void test_early_morning_belongs_to_previous_date() {
    assert(belongsToPreviousDate(2 * 60));
    assert(!belongsToPreviousDate(22 * 60));
}

static void test_buffer_fifo_and_drop_oldest_when_full() {
    ReadingBuffer<3> b;
    for (uint32_t i = 1; i <= 4; i++) b.push({i, 0, 0});
    assert(b.size() == 3);
    assert(b.at(0).epoch == 2);  // 1 was dropped
    assert(b.at(2).epoch == 4);
    b.dropFront(2);
    assert(b.size() == 1 && b.at(0).epoch == 4);
    b.dropFront(5);
    assert(b.size() == 0);
}

static void test_format_row_positive_and_negative() {
    char buf[96];
    formatRow(buf, sizeof buf, "2026-10-05T02:00:00", {1791190800u, 2141, 5210});
    assert(strcmp(buf, "2026-10-05T02:00:00,1791190800,21.41,52.10\n") == 0);
    formatRow(buf, sizeof buf, "2026-01-05T02:00:00", {1u, -205, 3007});
    assert(strcmp(buf, "2026-01-05T02:00:00,1,-2.05,30.07\n") == 0);
}

static void test_receiver_prefers_name_then_configured_then_last_good() {
    assert(pickReceiver(214, 201) == 214);  // the name wins over a stale memory
    assert(pickReceiver(0, 201) == 201);
    assert(pickReceiver(214, 0) == 214);
    assert(pickReceiver(0, 0) == 0);  // no route: never a guessed address
    assert(pickReceiver(214, 201, 50) == 214);
    assert(pickReceiver(0, 201, 50) == 50);  // a reflash with a new fixed address takes effect
    assert(pickReceiver(0, 0, 50) == 50);
}

static void test_flash_written_only_when_a_working_address_changes() {
    assert(shouldRemember(214, 201));
    assert(shouldRemember(214, 0));
    assert(!shouldRemember(214, 214));
    assert(!shouldRemember(0, 201));
}

static void test_hello_line_fits_and_holds_no_secret() {
    char buf[140];
    int n = formatHello(buf, sizeof buf, "1.0.0", 1, 3999, 12345, -11, -67, 1200);
    assert(n > 0 && n < (int)sizeof buf);
    assert(strcmp(buf, "/bedside/hello?fw=1.0.0&reset=1&rows=3999&fails=12345&code=-11&rssi=-67&readfail=1200") == 0);
    assert(strstr(buf, "oken") == nullptr);
}

int main() {
    test_window_is_2130_to_0730();
    test_early_morning_belongs_to_previous_date();
    test_buffer_fifo_and_drop_oldest_when_full();
    test_format_row_positive_and_negative();
    test_receiver_prefers_name_then_configured_then_last_good();
    test_flash_written_only_when_a_working_address_changes();
    test_hello_line_fits_and_holds_no_secret();
    printf("logic tests passed\n");
    return 0;
}
