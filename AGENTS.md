# AGENTS.md: set this bedside sensor up for your human

You are an AI coding agent (Claude Code, Codex, Gemini CLI, Cursor, or any other) and your human
wants the bedside temperature and humidity logger from the video. This file is the whole job.
Work through it top to bottom from the repo root and run every check. Do everything yourself
except the parts marked **HUMAN**; for those, ask, wait for the answer, and go on.

**Done means:**
1. The board's power-up check-in is in the receiver log (a `GET /bedside/hello?...` line from
   the sensor's address with status `200`), sent from the spot where the sensor will live, and
   the serial output showed a real reading (`now 21.40 C, 48.2 %RH`) and `clock synced`.
2. The receiver starts at login (step 6), or the human chose not to and knows it must be running.
3. The morning after the first night, after 07:30, a file `*_night-YYYY-MM-DD.csv` is in
   `~/bedside-sensor/nights/` on the receiver computer: about 1,200 rows for a full night, fewer
   if the sensor went in after 21:30. You cannot wait for this one: tell the human what to look
   for, or check it yourself in a later session.

## What this is

An Adafruit QT Py ESP32 Pico with an SHT41 sensor on a short STEMMA QT cable. From 21:30 to
07:30 it reads temperature and humidity every 30 s with its Wi-Fi **off** and keeps the readings
in RAM (about 3.3 nights' worth). After 07:30 it turns Wi-Fi on, finds the receiver computer by
its `.local` name, POSTs the night to `receiver/bedside_receiver.py` (port 7690, shared token),
and turns Wi-Fi off. The only other radio use: one connection at power-up to set its clock, plus
a short check-in after problems. Failed uploads retry hourly.

```
QT Py ESP32 + SHT41  ── Wi-Fi after 07:30 ──>  bedside_receiver.py on the receiver computer
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
- Changing what starts at login (step 6) needs the human's yes.
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
   - `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then `export PATH="$HOME/.local/bin:$PATH"`
     in each later command (or a new shell).
   - `c++` or `python3` on macOS: **HUMAN** runs `xcode-select --install` and clicks Install.
     Linux: **HUMAN** runs `sudo apt install build-essential python3` (or their distro's equivalent).
   - Python must be 3.9 or newer: `python3 -c 'import sys; print(sys.version_info >= (3, 9))'` prints `True`.
2. **Board support.** Check for about 6 GB free (`df -h ~`), then run
   `./esp32_sensor/firmware.sh setup`. The first run downloads about 1.7 GB (the ESP32 core and
   its compilers; a few minutes; the progress output is long) and pulls in some unrelated Adafruit
   display libraries as dependencies, which is normal. It must end with lines starting
   `esp32:esp32` and `Adafruit SHT4x Library`, then `setup ok`.
3. **Tests.** `./check.sh` must end with `all checks passed`. It runs the firmware logic tests,
   the receiver tests and a full compile for the board with the example settings (look for
   `Sketch uses ... bytes (33%) of program storage space`). The first compile takes a minute or two.
4. **HUMAN: which computer receives the data?** Ask them, before anything is set up:
   - "Is this the computer that will be on and on your home network most mornings?" The
     receiver must run there. If it is asleep at 07:30, the sensor retries every hour and holds
     about three nights, so a laptop that is open sometime during the day works; one that is
     away from home for days does not. If they have an always-on computer (a desktop, a home
     server) and this is not it, see "Receiver on another computer" below, then continue.
   - macOS: in a moment Python starts accepting connections. If a dialog asks whether Python
     may accept incoming connections, they must choose **Allow**. Step 5's `--check` reads the
     firewall's setting for Python; the real proof is the sensor's check-in in step 9.
     Linux: open TCP port 7690 if a firewall is on (`sudo ufw allow 7690/tcp`), and make sure
     `avahi-daemon` is running (the sensor finds the computer by its `.local` name).
   - The sensor and this computer must be on the same main network: guest networks and
     "client isolation" stop devices on the Wi-Fi from reaching each other.
5. **Receiver.** Make the shared token, start the receiver in the background, and test it:
   - First, is one already running? `curl -s http://127.0.0.1:7690/health` must print nothing.
     If it prints `ok`: a receiver from an earlier attempt with `~/bedside-sensor/receiver.pid`
     is stopped with `kill "$(cat ~/bedside-sensor/receiver.pid)" && rm ~/bedside-sensor/receiver.pid`;
     the login service from step 6 is kept (skip to the `--test-upload` line below). Anything
     else: find it with `lsof -nP -iTCP:7690 -sTCP:LISTEN` and ask the human before stopping it.
   - `python3 receiver/bedside_receiver.py --make-token` prints `ok token created at ...` (or
     `already exists`).
   - `mkdir -p ~/bedside-sensor && (nohup python3 receiver/bedside_receiver.py >> ~/bedside-sensor/receiver.log 2>&1 & echo $! > ~/bedside-sensor/receiver.pid)`
   - `sleep 2; curl -sf http://127.0.0.1:7690/health || tail -n 5 ~/bedside-sensor/receiver.log`
     must print `ok` (otherwise the log lines say why).
   - `python3 receiver/bedside_receiver.py --test-upload` must start with `ok` and report the
     check-in answered 200, a wrong token refused with 401, and a test night saved, identical to
     what was sent, then deleted. These are the same requests the sensor makes.
   - `python3 receiver/bedside_receiver.py --check`: every line `ok`. It prints the lowercase
     `.local` name the sensor will look for (mDNS names ignore case), the macOS firewall's
     setting for Python, and this computer's LAN address. A `WARN` is explained in the table.
6. **HUMAN: start the receiver at login?** Recommended, and best done now: a receiver started
   from your shell can stop when your session ends, and then the flash in step 9 and every
   morning upload fail. Explain that it adds a login item (macOS: a launchd agent; Linux: a
   systemd user service); `receiver/install_service.sh --print` shows the exact file, changing
   nothing. With a yes, run `receiver/install_service.sh`. It stops the copy from
   step 5, copies the receiver to `~/bedside-sensor/`, and must end with
   `ok receiver answering on port 7690`. On Linux it also prints a `loginctl enable-linger`
   command; it needs `sudo`, so the human runs it if this computer is often logged out.
   Then `python3 receiver/bedside_receiver.py --check` again: all `ok`.
   With a no: before steps 9 and 12, check `curl -s http://127.0.0.1:7690/health` prints `ok`,
   and restart it with step 5's commands if not. Tell the human nights only arrive while it
   runs, and give them the line to start it after every restart or login, from this folder:
   `mkdir -p ~/bedside-sensor && (nohup python3 receiver/bedside_receiver.py >> ~/bedside-sensor/receiver.log 2>&1 & echo $! > ~/bedside-sensor/receiver.pid)`
   (or say yes to step 6 later).
7. **HUMAN: Wi-Fi settings.** Ask the human to run, in their own terminal, from this folder:
   `./esp32_sensor/make_device_config.sh`
   It asks for the name of a **2.4 GHz** Wi-Fi network (the board cannot join 5 GHz-only
   networks) and its password (not shown), and fills in the token, the receiver's `.local`
   name and the time zone itself. It prints `wrote .../device_config.h (mode 600)`, the name and
   the time zone. Check them without opening the file:
   `test -f esp32_sensor/device_config.h && grep -E '^#define (RECEIVER_HOST|TZ_INFO|RECEIVER_IP|RECEIVER_PORT)' esp32_sensor/device_config.h || echo "MISSING: the human has not run make_device_config.sh yet"`
   `RECEIVER_HOST` must be the same name as step 5's `--check` line, without `.local`. The time
   zone is a POSIX rule such as `CST6CDT,M3.2.0,M11.1.0`; `UTC0` is right only if they really
   live on UTC. Then `./esp32_sensor/firmware.sh build` must end with
   `build ok (with your device_config.h)`. `build ok (example settings only ...)` means the
   config is missing: do not go on.
8. **HUMAN: wire it and plug it in.** Ask them to:
   - Connect the SHT41 to the QT Py with the STEMMA QT cable (it only fits one way). If they will
     use the printed case, use the SHT41 socket at the end **away from** its small green LED.
   - Plug the QT Py straight into this computer with a USB-C **data** cable. Not through a hub,
     and not a charge-only cable: in the video a bad cable cost 40 minutes. If they have
     several cables, use the one that came with a phone or that they know moves data.
   Then run `./esp32_sensor/firmware.sh ports`: it must list exactly one port. Nothing listed:
   see the table (cable first).
9. **Flash.** Check the receiver is up (`curl -s http://127.0.0.1:7690/health` prints `ok`;
   if the receiver is on another computer, check there). Then run
   `./esp32_sensor/firmware.sh flash` yourself. It compiles, uploads (ends with
   `Hard resetting via RTS pin...`) and then shows 40 s of the board's serial output. You want,
   in order: `SHT41 found`, `now NN.NN C, NN.N %RH`, `Wi-Fi connected`,
   `receiver: <address> (last good ...)`, `hello /bedside/hello?...: HTTP 200`, `clock synced`.
   If the output is empty, ask the human to press the board's **RST** button and run
   `./esp32_sensor/firmware.sh monitor 40`.
   Then confirm on the receiver side: `grep 'bedside/hello' ~/bedside-sensor/receiver.log | tail -n 3`
   shows a line from the sensor's address (not `127.0.0.1`, which was your test) with `200`.
   That proves the Wi-Fi, the name lookup and the route to the receiver; `clock synced` on
   serial proves the clock. Uploads use the same route after 07:30.
10. **HUMAN, optional: sensor check.** `./esp32_sensor/firmware.sh bench` uploads a test that
    prints a reading every second for 30 s while the human pinches the sensor or breathes on it:
    temperature and humidity should climb within seconds. **Then flash the real firmware again**
    (step 9). Skip this if step 9 printed a sensible reading.
11. **HUMAN: the case (optional).** The print files are ready in `enclosure/print/`: four
    parts (`sensor_pod_tray`, `sensor_pod_lid`, `board_case_tray`, `board_case_lid`), as `.stl`
    or `.3mf`, already oriented. PLA, 0.2 mm layers, no supports; about 20 minutes and 8 g in
    all. The SHT41 sits on four pins in the vented pod with its cable socket at the pod's open
    end; the QT Py sits on the ledges in the case with its USB-C port through the end opening.
    Lids press on; the video's were superglued. Put a small piece of black tape over the SHT41's
    green power LED (it has no off switch); keep the tape off the sensor chip itself.
    No printer: the bare boards work too. Keep the sensor away from the board and the charger
    so their warmth does not bias it (the 100 mm cable is for that). The case can come later:
    don't hold up step 12 for it.
12. **HUMAN: by the bed.** Ask them to unplug the board, put it by the bed and power it from a
    USB charger, soon: unplugging clears the readings held in RAM, so after 21:30 every minute
    unplugged is a gap in tonight's file. Then wait about 30 s and run
    `grep 'bedside/hello' ~/bedside-sensor/receiver.log | tail -n 2`: a new line **from the
    sensor's address** (not `127.0.0.1`) with `reset=1` means it booted there, joined the Wi-Fi
    and reached the receiver. No new line within two minutes: the Wi-Fi does not reach that spot
    well, or see the table.
13. **Tell the human what happens next.** Readings start at 21:30. After 07:30 the night appears
    in `~/bedside-sensor/nights/` as `<arrival time>_night-<the evening's date>.csv`, columns
    `time_local,epoch,temp_c,rh_pct`, about 1,200 rows for a full night. On the night clocks go
    back, `time_local` repeats an hour: sort and plot by `epoch`. Check the first file the next
    day: `ls -l ~/bedside-sensor/nights/ && tail -n 3 ~/bedside-sensor/receiver.log`.

### Receiver on another computer

The receiver is one stdlib Python file; the other computer needs only `python3` 3.9+ and this
repo. On that computer (an agent there, or the human): steps 4, 5 and 6. Then copy its token to
this computer without showing it, for example
`mkdir -p ~/.config/bedside_receiver && scp OTHER:.config/bedside_receiver/token ~/.config/bedside_receiver/token && chmod 600 ~/.config/bedside_receiver/token`,
and in step 7 the human runs `RECEIVER_HOST=<the other computer's name from its --check> ./esp32_sensor/make_device_config.sh`.
Read that computer's `~/bedside-sensor/receiver.log` in steps 9 and 12, and look for the nights there.

## When it does not work

| What you see | Cause and fix |
|---|---|
| `firmware.sh ports` lists nothing | Charge-only cable, a hub, or a loose plug. Swap to a known-good USB-C **data** cable straight into the computer. Linux: add the user to the `dialout` group (`sudo usermod -aG dialout $USER`, then log out and in). Old macOS without a driver for the board's CH9102F chip: install WCH's CH34x driver |
| Upload fails with `Failed to connect to ESP32 ... no sync reply` or `No serial data received` | Same causes as above, cable first. If a good cable still fails: hold the board's **BOOT** button, press and release **RST**, release BOOT, run `flash` again, then press RST once it finishes |
| Upload starts, then dies a few KB in (`The chip stopped responding`, `Serial data stream stopped`) | A bad cable or hub. This is what happened in the video: the cable passed power and short commands but dropped every long write. A known-good data cable plugged directly in fixed it |
| `Resource busy` / port in use | Another program has the port open (Arduino IDE, `screen`, another monitor). Close it |
| `several serial ports, pick one` | Run with `PORT=/dev/... ./esp32_sensor/firmware.sh flash`, choosing the port that appeared when the board was plugged in |
| `SHT41 NOT FOUND` | STEMMA QT cable not fully seated at either end. Re-seat it; `firmware.sh bench` scans the bus (the SHT41 answers at `0x44`) |
| `Wi-Fi NOT connected`, `clock NOT synced` | Wrong Wi-Fi name or password, or a 5 GHz-only network, or too far from the router. HUMAN reruns step 7, then flash again |
| `mDNS found no NAME.local` and `receiver: 0.0.0.0` | The sensor cannot find this computer by name: the name is wrong (receiver on another computer: `RECEIVER_HOST=thatname ./esp32_sensor/make_device_config.sh`), or the router blocks mDNS. Fix for the second: give this computer a fixed address in the router (DHCP reservation), then HUMAN runs `RECEIVER_IP=<that address> ./esp32_sensor/make_device_config.sh`; flash again |
| `--check` says `WARN macOS firewall is on and Python is not listed yet` or `MISSING macOS firewall blocks Python` | The human allows it: answer Allow when macOS asks, or System Settings, Network, Firewall, Options, set Python to Allow incoming connections. Then `--check` again |
| `--check` says `WARN NAME.local does not resolve` | Linux without `avahi-daemon`/`nss-mdns`: start avahi (`sudo systemctl enable --now avahi-daemon`) or use the `RECEIVER_IP` fix above. On macOS this should not happen |
| `hello ...: HTTP -1` | Nothing answered at that address: receiver not running (step 6), the macOS firewall blocking Python (System Settings, Network, Firewall, Options: allow Python) or a Linux firewall blocking port 7690, or the address is stale |
| `cannot listen on port 7690` in the receiver log, or `--test-upload` says 401 or "not in" the folder | Another receiver is already running (an earlier attempt or the login service). Use the one that is running, or stop it (`receiver/install_service.sh --remove`, or `kill "$(cat ~/bedside-sensor/receiver.pid)"`) and start again |
| `upload night ...: HTTP 401` | Token mismatch: the token file was remade after flashing. HUMAN reruns step 7, then flash again |
| `HTTP 403 forbidden network` | The sensor's address is not a private LAN address; the receiver only accepts 10.x, 172.16-31.x and 192.168.x |
| No file in the morning | Receiver not running (`curl -s http://127.0.0.1:7690/health`; step 6), computer asleep or off (the sensor retries hourly and keeps about 3 nights), or no hello lines at all (the board has no power or no Wi-Fi at the bed). Read `~/bedside-sensor/receiver.log` for `POST /bedside/temp` lines and their status |
| Hello lines with `readfail=` above 0 | The sensor stopped answering at night (usually a loose STEMMA QT cable). Re-seat it; it recovers on its own |
| `reset=6` or `reset=4` in hello lines | The watchdog or a crash restarted the board; readings held in RAM were lost. Rare; note it and look for a pattern |
| Hours or dates look shifted | Wrong time zone. HUMAN reruns step 7 with `TZ_INFO='<POSIX rule>'` in front, then flash again |
| Readings run warm | The sensor is too close to the board, the charger or the case wall. Use the separate pod and the full 100 mm cable |
| `device_config.h has no TZ_INFO` when compiling | A config made by an older script. Rerun step 7 |

## Changing things

- Logging window: `START_MIN` and `END_MIN` in `esp32_sensor/logic.h` (and the window test in
  `esp32_sensor/test_logic.cpp`). Run `./check.sh`, then flash.
- Port: `--port` on the receiver (`PORT=<n> receiver/install_service.sh` for the login
  service), and the human reruns `RECEIVER_PORT=<n> ./esp32_sensor/make_device_config.sh`, then flash.
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
