# AGENTS.md: set this bedside sensor up for your human

You are an AI coding agent (Claude Code, Codex, Gemini CLI, Cursor, or any other) and your human
wants the bedside temperature and humidity logger from the video. This file is the whole job.
Work through it top to bottom from the repo root and run every check. Do everything yourself
except the parts marked **HUMAN**; for those, ask, wait for the answer, and go on.

**Done means:**
1. The board's power-up check-in is in the receiver log on this computer (a
   `GET /bedside/hello?...` line with status `200`), sent from the spot where the sensor will
   live, and the serial output showed a real reading (`now 21.40 C, 48.2 %RH`) and
   `clock synced`.
2. The receiver starts at login (step 10).
3. The morning after the first night, after 07:30, a file `*_night-YYYY-MM-DD.csv` with about
   1,200 rows is in `~/bedside-sensor/nights/`. You cannot wait for this one: tell the human
   what to look for, or check it yourself in a later session.

## What this is

An Adafruit QT Py ESP32 Pico with an SHT41 sensor on a short STEMMA QT cable. From 21:30 to
07:30 it reads temperature and humidity every 30 s with its Wi-Fi **off** and keeps the readings
in RAM (about 3.3 nights' worth). After 07:30 it turns Wi-Fi on, finds this computer by its
`.local` name, POSTs the night to `receiver/bedside_receiver.py` (port 7690, shared token), and
turns Wi-Fi off. The only other radio use: one connection at power-up to set its clock, plus a
short check-in after problems. Failed uploads retry hourly.

```
QT Py ESP32 + SHT41  ── Wi-Fi after 07:30 ──>  bedside_receiver.py on this computer
 (by the bed, USB power)                         saves ~/bedside-sensor/nights/<ts>_night-<date>.csv
```

## Rules

- Never print, log, paste or `cat` `esp32_sensor/device_config.h` (it holds the Wi-Fi password
  and the token) or the token file `~/.config/bedside_receiver/token`. Never ask the human to
  paste their Wi-Fi password into the chat; they type it into `make_device_config.sh` in their
  own terminal. The commands below are written so you never need to see a secret. Never commit
  `device_config.h` (it is gitignored; keep it that way).
- If a check fails, read the output and diagnose with the table at the end before changing
  anything. Do not edit the firmware to get past an error.
- Changing what starts at login (step 10) needs the human's yes.
- You will write outside this folder (`~/bedside-sensor`, `~/.config/bedside_receiver`), open a
  network port (7690) and download packages. If your sandbox blocks that, ask the human to allow it.
- Long-running commands: never run `./esp32_sensor/firmware.sh monitor 0` or `tail -f`; they
  never return. Every command below returns on its own.

## Steps

1. **Tools.** Run:
   `for t in git python3 uv arduino-cli c++ curl perl; do command -v "$t" >/dev/null || echo "MISSING $t"; done`
   No output means all present. Install what is missing:
   - `arduino-cli`: macOS `brew install arduino-cli`; Linux
     `curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=$HOME/.local/bin sh`
     (make sure `~/.local/bin` is on `PATH`).
   - `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new shell.
   - `c++` or `python3` on macOS: **HUMAN** runs `xcode-select --install` and clicks Install.
     Linux: **HUMAN** runs `sudo apt install build-essential python3` (or their distro's equivalent).
   - Python must be 3.9 or newer: `python3 -c 'import sys; print(sys.version_info >= (3, 9))'` prints `True`.
2. **Board support.** `./esp32_sensor/firmware.sh setup`. The first run downloads the ESP32 core
   (several hundred MB, a few minutes). It must end with lines starting `esp32:esp32` and
   `Adafruit SHT4x Library`, then `setup ok`.
3. **Tests.** `./check.sh` must end with `all checks passed`. It runs the firmware logic tests,
   the receiver tests and a full compile for the board with the example settings (look for
   `Sketch uses ... bytes (33%) of program storage space`). The first compile takes a minute or two.
4. **Receiver.** Make the shared token, start the receiver in the background, and test it:
   - `python3 receiver/bedside_receiver.py --make-token` prints `ok token created at ...` (or
     `already exists`).
   - `mkdir -p ~/bedside-sensor && (nohup python3 receiver/bedside_receiver.py >> ~/bedside-sensor/receiver.log 2>&1 &)`
   - `for i in $(seq 10); do curl -sf http://127.0.0.1:7690/health && break; sleep 1; done`
     must print `ok`.
   - `python3 receiver/bedside_receiver.py --test-upload` must print `ok hello check-in 200;
     wrong token refused 401; test night saved ...`. This is the same request the sensor makes.
   - `python3 receiver/bedside_receiver.py --check`: every line `ok` (a `WARN` about `.local` is
     explained in the table). Note the `.local` name it prints: the sensor looks for that name.
   To restart it later: `pkill -f bedside_receiver.py ;` then the `nohup` command again.
5. **HUMAN: this computer.** Tell them:
   - It must be on, awake and on the same home network as the sensor at 07:30 most mornings. If
     it is asleep, the sensor retries every hour and holds about three nights, so a computer that
     wakes later in the day still gets the data. A laptop that sleeps all night with its lid shut
     is fine as long as it is open and on the network sometime during the day.
   - macOS: if asked whether Python may accept incoming connections, choose Allow.
     Linux: open TCP port 7690 if a firewall is on (`sudo ufw allow 7690/tcp`), and make sure
     `avahi-daemon` is running (the sensor finds this computer by its `.local` name).
   - Guest networks and "client isolation" stop devices on the Wi-Fi from reaching each other;
     the sensor and this computer must be on the main network.
6. **HUMAN: Wi-Fi settings.** Ask the human to run, in their own terminal, from this folder:
   `./esp32_sensor/make_device_config.sh`
   It asks for the name of a **2.4 GHz** Wi-Fi network (the board cannot join 5 GHz-only
   networks) and its password (not shown), and fills in the token, this computer's `.local`
   name and the time zone itself. It ends with `wrote .../device_config.h (mode 600)` and shows
   the name and time zone. Check them without opening the file:
   `grep -E '^#define (RECEIVER_HOST|TZ_INFO|RECEIVER_IP)' esp32_sensor/device_config.h`
   The time zone is a POSIX rule such as `CST6CDT,M3.2.0,M11.1.0`; `UTC0` is right only if they
   really live on UTC. Then `./esp32_sensor/firmware.sh build` must end with `build ok`.
7. **HUMAN: wire it and plug it in.** Ask them to:
   - Connect the SHT41 to the QT Py with the STEMMA QT cable (it only fits one way). If they will
     use the printed case, use the SHT41 socket at the end **away from** its small green LED.
   - Plug the QT Py straight into this computer with a USB-C **data** cable. Not through a hub,
     and not a charge-only cable: in the video a bad cable cost 40 minutes. If they have
     several cables, use the one that came with a phone or that they know moves data.
   Then run `./esp32_sensor/firmware.sh ports`: it must list exactly one port. Nothing listed:
   see the table (cable first).
8. **Flash.** Run `./esp32_sensor/firmware.sh flash` yourself. It compiles, uploads (ends
   with `Hard resetting via RTS pin...`) and then shows 40 s of the board's serial output. You
   want, in order: `SHT41 found`, `now NN.NN C, NN.N %RH`, `Wi-Fi connected`,
   `receiver: <address> (last good ...)`, `hello /bedside/hello?...: HTTP 200`,
   `clock synced`. If the output is empty, ask the human to press the board's **RST** button
   and run `./esp32_sensor/firmware.sh monitor 40`.
   Then confirm on this side: `grep 'bedside/hello' ~/bedside-sensor/receiver.log | tail -n 3`
   shows a line from the sensor's address (not `127.0.0.1`, which was your test) with `200`.
   That proves the Wi-Fi, the name lookup, the route to this computer and the clock. Uploads use
   the same route after 07:30.
9. **HUMAN, optional: sensor check.** `./esp32_sensor/firmware.sh bench` uploads a test that
   prints a reading every second for 30 s while the human pinches the sensor or breathes on it:
   temperature and humidity should climb within seconds. **Then flash the real firmware again**
   (step 8). Skip this if step 8 printed a sensible reading.
10. **HUMAN: start the receiver at login?** Explain that otherwise the receiver stops when this
    computer restarts and nights stop arriving. With a yes, run
    `receiver/install_service.sh` (macOS: a launchd agent; Linux: a systemd user service). It
    stops the copy from step 4, copies the receiver to `~/bedside-sensor/`, and must end with
    `ok receiver answering on port 7690`. On Linux it also prints a `loginctl enable-linger`
    command; it needs `sudo`, so the human runs it if this computer is often logged out.
    Then `python3 receiver/bedside_receiver.py --check` again: all `ok`.
11. **HUMAN: the case (optional).** The print files are ready in `enclosure/print/`: four
    parts (`sensor_pod_tray`, `sensor_pod_lid`, `board_case_tray`, `board_case_lid`), as `.stl`
    or `.3mf`, already oriented. PLA, 0.2 mm layers, no supports; about 20 minutes and 8 g in
    all. The SHT41 sits on four pins in the vented pod with its cable socket at the pod's open
    end; the QT Py sits on the ledges in the case with its USB-C port through the end opening.
    Lids press on; the video's were superglued. Put a small piece of black tape over the SHT41's
    green power LED (it has no off switch); keep the tape off the sensor chip itself.
    No printer: the bare boards work too. Keep the sensor away from the board and the charger
    so their warmth does not bias it (the 100 mm cable is for that).
12. **HUMAN: by the bed.** Ask them to unplug the board, put it by the bed and power it from a
    USB charger. Then wait about 30 s and run
    `grep 'bedside/hello' ~/bedside-sensor/receiver.log | tail -n 2`: a new line with `reset=1`
    means it booted there, joined the Wi-Fi and reached this computer. No new line within two
    minutes: the Wi-Fi does not reach that spot well, or see the table.
13. **Tell the human what happens next.** Readings start at 21:30. After 07:30 the night appears
    in `~/bedside-sensor/nights/` as `<arrival time>_night-<the evening's date>.csv`, columns
    `time_local,epoch,temp_c,rh_pct`, about 1,200 rows. On the night clocks go back, `time_local`
    repeats an hour: sort and plot by `epoch`. Check the first file the next day:
    `ls -l ~/bedside-sensor/nights/ && tail -n 3 ~/bedside-sensor/receiver.log`.

## When it does not work

| What you see | Cause and fix |
|---|---|
| `firmware.sh ports` lists nothing | Charge-only cable, a hub, or a loose plug. Swap to a known-good USB-C **data** cable straight into the computer. Linux: add the user to the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and in). Old macOS without a driver for the board's CH9102F chip: install WCH's CH34x driver |
| Upload fails with `Failed to connect to ESP32 ... no sync reply` or `No serial data received` | Same causes as above, cable first. If a good cable still fails: hold the board's **BOOT** button, press and release **RST**, release BOOT, run `flash` again, then press RST once it finishes |
| Upload starts, then dies a few KB in (`The chip stopped responding`, `Serial data stream stopped`) | A bad cable or hub. This is what happened in the video: the cable passed power and short commands but dropped every long write. A known-good data cable plugged directly in fixed it |
| `Resource busy` / port in use | Another program has the port open (Arduino IDE, `screen`, another monitor). Close it |
| `several serial ports, pick one` | Run with `PORT=/dev/... ./esp32_sensor/firmware.sh flash`, choosing the port that appeared when the board was plugged in |
| `SHT41 NOT FOUND` | STEMMA QT cable not fully seated at either end. Re-seat it; `firmware.sh bench` scans the bus (the SHT41 answers at `0x44`) |
| `Wi-Fi NOT connected`, `clock NOT synced` | Wrong Wi-Fi name or password, or a 5 GHz-only network, or too far from the router. HUMAN reruns step 6, then flash again |
| `mDNS found no NAME.local` and `receiver: 0.0.0.0` | The sensor cannot find this computer by name: the name is wrong (receiver on another computer: `RECEIVER_HOST=thatname ./esp32_sensor/make_device_config.sh`), or the router blocks mDNS. Fix for the second: give this computer a fixed address in the router (DHCP reservation), then HUMAN runs `RECEIVER_IP=<that address> ./esp32_sensor/make_device_config.sh`; flash again |
| `--check` says `WARN NAME.local does not resolve` | Linux without `avahi-daemon`/`nss-mdns`: start avahi (`sudo systemctl enable --now avahi-daemon`) or use the `RECEIVER_IP` fix above. On macOS this should not happen |
| `hello ...: HTTP -1` | Nothing answered at that address: receiver not running, computer firewall blocking port 7690, or the address is stale |
| `upload night ...: HTTP 401` | Token mismatch: the token file was remade after flashing. HUMAN reruns step 6, then flash again |
| `HTTP 403 forbidden network` | The sensor's address is not a private LAN address; the receiver only accepts 10.x, 172.16-31.x and 192.168.x |
| No file in the morning | Receiver not running (`curl -s http://127.0.0.1:7690/health`; step 10), computer asleep or off (the sensor retries hourly and keeps about 3 nights), or no hello lines at all (the board has no power or no Wi-Fi at the bed). Read `~/bedside-sensor/receiver.log` for `POST /bedside/temp` lines and their status |
| Hello lines with `readfail=` above 0 | The sensor stopped answering at night (usually a loose STEMMA QT cable). Re-seat it; it recovers on its own |
| `reset=6` or `reset=4` in hello lines | The watchdog or a crash restarted the board; readings held in RAM were lost. Rare; note it and look for a pattern |
| Hours or dates look shifted | Wrong time zone. HUMAN reruns step 6 with `TZ_INFO='<POSIX rule>'` in front, then flash again |
| Readings run warm | The sensor is too close to the board, the charger or the case wall. Use the separate pod and the full 100 mm cable |
| `device_config.h has no TZ_INFO` when compiling | A config made by an older script. Rerun step 6 |

## Changing things

- Logging window: `START_MIN` and `END_MIN` in `esp32_sensor/logic.h` (and the window test in
  `esp32_sensor/test_logic.cpp`). Run `./check.sh`, then flash.
- Port: `--port` on the receiver (and in `install_service.sh`), plus `#define RECEIVER_PORT` in
  `device_config.h`.
- Where nights are saved: `--out` on the receiver.
- The case: `enclosure/enclosure.py` (CadQuery). `./check.sh --enclosure` rebuilds the files
  in `enclosure/print/` and fails if either board would touch its case.

## Map

- `esp32_sensor/esp32_sensor.ino`: the firmware. `logic.h`: the testable parts (window,
  buffer, CSV rows). `test_logic.cpp`: their tests. `bench/`: the one-reading-a-second test.
- `esp32_sensor/firmware.sh`: setup, build, ports, flash, monitor, bench.
  `make_device_config.sh`: writes the private `device_config.h`.
- `receiver/bedside_receiver.py`: the receiver, one stdlib-only file; `--make-token`, `--check`,
  `--test-upload`, `--print-name`. `install_service.sh`: start at login.
- `enclosure/`: the case model, Adafruit's board models in `ref/`, print files in `print/`.
- `check.sh`: every test that needs no hardware.
- `README.md`: the human-facing overview, parts and costs.
