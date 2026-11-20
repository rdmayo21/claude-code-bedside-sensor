#!/bin/bash
# Run every check that needs no hardware. Usage: ./check.sh [--enclosure]
#   firmware logic tests (c++), receiver tests (pytest via uv), firmware compile for the board
#   --enclosure  also rebuild the case and check that neither board touches it (CadQuery; the
#                first run downloads it, which takes a few minutes)
set -uo pipefail
cd "$(dirname "$0")"
failed=()

run() {
    local name=$1; shift
    echo "== $name"
    if "$@"; then echo "   pass"; else echo "   FAIL"; failed+=("$name"); fi
}

tmp=$(mktemp -d)
run "firmware logic tests" bash -c "c++ -std=c++17 esp32_sensor/test_logic.cpp -o '$tmp/t' && '$tmp/t'"
run "receiver tests" bash -c "uv run --quiet --no-project --with pytest pytest -q -p no:cacheprovider receiver"
run "firmware compile" ./esp32_sensor/firmware.sh build
if [ "${1:-}" = "--enclosure" ]; then
    run "enclosure fit check" bash -c "cd enclosure && uv run --quiet --no-project --python 3.12 --with cadquery python enclosure.py"
fi
rm -rf "$tmp"

if [ ${#failed[@]} -gt 0 ]; then
    echo "FAILED: ${failed[*]}"
    exit 1
fi
echo "all checks passed"
