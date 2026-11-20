// Template for device_config.h (gitignored). Don't fill it in by hand: run
// ./make_device_config.sh, which asks for the Wi-Fi password without showing it and copies
// the receiver token without printing it. `./firmware.sh build` compiles against this file
// when device_config.h does not exist yet.
#pragma once

#define WIFI_SSID "your-2.4GHz-network"
#define WIFI_PASS "your-wifi-password"
#define RECEIVER_TOKEN "token-from-the-receiver"
#define RECEIVER_HOST "your-computer"  // the receiver computer's mDNS name, without .local
#define TZ_INFO "UTC0"                 // POSIX time zone, e.g. "EST5EDT,M3.2.0,M11.1.0"

// Optional. Only if the sensor cannot find the computer by name (some routers block mDNS):
// give the computer a fixed address in your router, then put it here.
// #define RECEIVER_IP "192.168.1.50"
// #define RECEIVER_PORT 7690
