#!/bin/bash
# Writes esp32_sensor/device_config.h (gitignored, mode 600). The HUMAN runs this in their own
# terminal: it asks for the Wi-Fi name and password (the password is not shown) and fills in
# the rest itself: the receiver token (copied from its file, never printed), this computer's
# network name, and this computer's time zone.
#
#   ./make_device_config.sh
#
# Optional overrides, as environment variables:
#   RECEIVER_HOST=name   the receiver runs on another computer (its mDNS name, without .local)
#   TOKEN_FILE=path      token file (default ~/.config/bedside_receiver/token)
#   TZ_INFO='...'        POSIX time zone string, if the detected one is wrong
#   RECEIVER_IP=a.b.c.d  fixed address, only if the sensor cannot find the computer by name
#   RECEIVER_PORT=n      the receiver listens on a port other than 7690
set -euo pipefail
cd "$(dirname "$0")"

token_file=${TOKEN_FILE:-$HOME/.config/bedside_receiver/token}
if [ ! -s "$token_file" ]; then
    echo "no receiver token at $token_file" >&2
    echo "make one first:  python3 receiver/bedside_receiver.py --make-token" >&2
    exit 1
fi

host=${RECEIVER_HOST:-$(python3 ../receiver/bedside_receiver.py --print-name)}
host=${host%.local}
# mDNS names are case-insensitive; lowercase is what the ESP32 lookup was tested with.
host=$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')
[ -n "$host" ] || { echo "could not work out this computer's network name; set RECEIVER_HOST" >&2; exit 1; }

# The last line of a modern zoneinfo file is the POSIX rule the ESP32 needs.
tz=${TZ_INFO:-$(tail -n 1 /etc/localtime 2>/dev/null | LC_ALL=C tr -d '\0' || true)}
if ! printf '%s' "$tz" | LC_ALL=C grep -Eq '^[A-Za-z<][A-Za-z0-9<>+:,./-]*[0-9][A-Za-z0-9<>+:,./-]*$'; then
    echo "could not read this computer's time zone as a POSIX rule." >&2
    echo "set it yourself, e.g.  TZ_INFO='EST5EDT,M3.2.0,M11.1.0' ./make_device_config.sh" >&2
    exit 1
fi

if [ -n "${RECEIVER_IP:-}" ] && ! printf '%s' "$RECEIVER_IP" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
    echo "RECEIVER_IP must look like 192.168.1.50" >&2
    exit 1
fi
if [ -n "${RECEIVER_PORT:-}" ] && ! printf '%s' "$RECEIVER_PORT" | grep -Eq '^[0-9]{1,5}$'; then
    echo "RECEIVER_PORT must be a number" >&2
    exit 1
fi

read -r -p "Wi-Fi network name (a 2.4 GHz network; the board cannot join 5 GHz): " ssid
[ -n "$ssid" ] || { echo "empty Wi-Fi name, stopping" >&2; exit 1; }
read -r -s -p "Wi-Fi password (not shown): " pass; echo
[ -n "$pass" ] || { echo "empty password, stopping" >&2; exit 1; }
token=$(tr -d '[:space:]' < "$token_file")

# Escape for a C string literal: backslash first, then double quote.
c_escape() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '%s' "$s"; }

umask 077
{
    echo '// Written by make_device_config.sh. Private: holds your Wi-Fi password. Never commit it.'
    echo '#pragma once'
    printf '#define WIFI_SSID "%s"\n' "$(c_escape "$ssid")"
    printf '#define WIFI_PASS "%s"\n' "$(c_escape "$pass")"
    printf '#define RECEIVER_TOKEN "%s"\n' "$(c_escape "$token")"
    printf '#define RECEIVER_HOST "%s"\n' "$(c_escape "$host")"
    printf '#define TZ_INFO "%s"\n' "$tz"
    if [ -n "${RECEIVER_IP:-}" ]; then printf '#define RECEIVER_IP "%s"\n' "$RECEIVER_IP"; fi
    if [ -n "${RECEIVER_PORT:-}" ]; then printf '#define RECEIVER_PORT %s\n' "$RECEIVER_PORT"; fi
} > device_config.h
chmod 600 device_config.h
unset pass token
echo "wrote $(pwd)/device_config.h (mode 600)"
echo "  receiver name: $host.local"
echo "  time zone:     $tz"
if [ -n "${RECEIVER_IP:-}" ]; then echo "  fixed address: $RECEIVER_IP"; fi
if [ -n "${RECEIVER_PORT:-}" ]; then echo "  port:          $RECEIVER_PORT"; fi
echo "next, from the repo folder: ./esp32_sensor/firmware.sh build"
