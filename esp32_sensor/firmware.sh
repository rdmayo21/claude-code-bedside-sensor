#!/bin/bash
# The bedside sensor firmware (Adafruit QT Py ESP32 Pico + SHT41), one command per step.
#   ./firmware.sh setup         install the ESP32 board support and the SHT4x library (once;
#                               downloads about 1.7 GB, needs about 6 GB of disk)
#   ./firmware.sh build         compile. Without device_config.h it compiles a throwaway copy
#                               with the example settings (proves the code builds; not flashable)
#   ./firmware.sh ports         list the serial ports a plugged-in board could be on
#   ./firmware.sh flash         compile with device_config.h, upload to the one plugged-in board,
#                               then show its serial output for 40 s (PORT=/dev/... to pick a port)
#   ./firmware.sh monitor [s]   show serial output for s seconds (default 30; 0 = until Ctrl-C)
#   ./firmware.sh bench         upload the bench test (a reading every second, no Wi-Fi) and
#                               show 30 s of it. Put the real firmware back with ./firmware.sh flash
set -euo pipefail
cd "$(dirname "$0")"
FQBN=esp32:esp32:adafruit_qtpy_esp32_pico
CORE_URL=https://espressif.github.io/arduino-esp32/package_esp32_index.json
CORE_VERSION=${CORE_VERSION:-3.3.12}       # the version this firmware was tested with
SHT4X_VERSION=${SHT4X_VERSION:-1.0.5}
BAUD=115200

need_cli() {
    command -v arduino-cli >/dev/null && return
    echo "arduino-cli missing. macOS: brew install arduino-cli" >&2
    echo "Linux: curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=\$HOME/.local/bin sh" >&2
    exit 1
}

list_ports() {
    local p
    for p in /dev/cu.usbserial* /dev/cu.usbmodem* /dev/cu.wch* /dev/cu.SLAB_USBtoUART* \
             /dev/ttyUSB* /dev/ttyACM*; do
        [ -e "$p" ] && echo "$p"
    done
    return 0
}

find_port() {
    if [ -n "${PORT:-}" ]; then echo "$PORT"; return; fi
    local ports=()
    while IFS= read -r p; do ports+=("$p"); done < <(list_ports)
    if [ ${#ports[@]} -eq 0 ]; then
        echo "no board found: plug the QT Py straight into this computer with a USB-C DATA cable" >&2
        echo "(a charge-only cable or a hub is the usual cause; on Linux, also the dialout group)" >&2
        exit 1
    elif [ ${#ports[@]} -gt 1 ]; then
        echo "several serial ports, pick one:  PORT=<port> ./firmware.sh $1" >&2
        printf '  %s\n' "${ports[@]}" >&2
        exit 1
    fi
    echo "${ports[0]}"
}

# Serial output for a fixed time, so an agent's shell gets its prompt back.
show_serial() {
    local port=$1 secs=$2
    if [ "$secs" = 0 ]; then
        exec arduino-cli monitor -p "$port" -c baudrate=$BAUD
    fi
    echo "--- serial output for ${secs} s (nothing? press the board's RST button) ---"
    sleep "$secs" | perl -e 'alarm shift; exec @ARGV' "$secs" \
        arduino-cli monitor -p "$port" -c baudrate=$BAUD || true
    echo "--- end of serial output ---"
}

case "${1:-}" in
    setup)
        need_cli
        if ! arduino-cli core list | grep -q '^esp32:esp32 '; then
            arduino-cli core update-index --additional-urls "$CORE_URL"
            arduino-cli core install "esp32:esp32@$CORE_VERSION" --additional-urls "$CORE_URL"
            arduino-cli cache clean  # the downloaded archives (~1.7 GB) are no longer needed
        fi
        if ! arduino-cli lib list | grep -q '^Adafruit SHT4x Library '; then
            arduino-cli lib update-index
            arduino-cli lib install "Adafruit SHT4x Library@$SHT4X_VERSION"
        fi
        arduino-cli core list | grep '^esp32:esp32 '
        arduino-cli lib list | grep '^Adafruit SHT4x Library '
        installed=$(arduino-cli core list | awk '$1 == "esp32:esp32" {print $2}')
        if [ "$installed" != "$CORE_VERSION" ]; then
            echo "note: ESP32 core $installed is installed; this firmware was tested with $CORE_VERSION"
        fi
        echo "setup ok"
        ;;
    build)
        need_cli
        if [ -f device_config.h ]; then
            arduino-cli compile --fqbn "$FQBN" .
        else
            tmp=$(mktemp -d)
            mkdir -p "$tmp/esp32_sensor"
            cp esp32_sensor.ino logic.h "$tmp/esp32_sensor/"
            cp device_config.example.h "$tmp/esp32_sensor/device_config.h"
            echo "(no device_config.h yet: compiling a throwaway copy with the example settings)"
            arduino-cli compile --fqbn "$FQBN" "$tmp/esp32_sensor"
            rm -rf "$tmp"
        fi
        echo "build ok"
        ;;
    ports)
        found=$(list_ports)
        if [ -n "$found" ]; then echo "$found"; else echo "no serial ports that look like a board"; fi
        ;;
    flash)
        need_cli
        [ -f device_config.h ] || { echo "no device_config.h: run ./make_device_config.sh first" >&2; exit 1; }
        port=$(find_port flash)
        echo "compiling"
        arduino-cli compile --fqbn "$FQBN" .
        echo "uploading to $port"
        arduino-cli upload --fqbn "$FQBN" -p "$port" .
        echo "flashed. Expect: 'SHT41 found', 'now NN.NN C, NN.N %RH', 'Wi-Fi connected',"
        echo "'receiver: <address>', 'hello ...: HTTP 200', 'clock synced'"
        show_serial "$port" "${SECONDS_TO_SHOW:-40}"
        ;;
    bench)
        need_cli
        port=$(find_port bench)
        arduino-cli compile --fqbn "$FQBN" bench
        echo "uploading the bench test to $port"
        arduino-cli upload --fqbn "$FQBN" -p "$port" bench
        echo "flashed. Expect: 'SHT41 found', then one reading a second. Put the real firmware back: ./firmware.sh flash"
        show_serial "$port" "${SECONDS_TO_SHOW:-30}"
        ;;
    monitor)
        need_cli
        show_serial "$(find_port monitor)" "${2:-30}"
        ;;
    *)
        sed -n '2,12p' "$(basename "$0")" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
