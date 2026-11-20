"""Bedside sensor receiver: takes each night's upload from the ESP32 and saves it as a CSV.

Runs on a computer on the same network as the sensor (macOS or Linux, Python 3.9+, stdlib only).
The sensor finds this computer by its mDNS name (<name>.local, see --print-name), POSTs one CSV
per night to /bedside/temp after 07:30 with a shared token, and sends a short
GET /bedside/hello?... at power-up and after problems, which shows up in this server's log.

    python3 bedside_receiver.py                 serve (port 7690, nights to ~/bedside-sensor/nights)
    python3 bedside_receiver.py --make-token    create the shared token file (never printed)
    python3 bedside_receiver.py --check         is everything ready? one line each, exit 1 if not
    python3 bedside_receiver.py --test-upload   post a fake night to the running receiver, check
                                                the saved file, then delete it
    python3 bedside_receiver.py --print-name    the name the sensor should look for

Saved files: <out>/<YYYYmmdd-HHMMSS>_night-<YYYY-MM-DD>.csv, named by the evening the night
started, with the header time_local,epoch,temp_c,rh_pct.
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 7690
DEFAULT_OUT = Path.home() / "bedside-sensor" / "nights"
DEFAULT_TOKEN_FILE = Path.home() / ".config" / "bedside_receiver" / "token"
MAX_BODY_BYTES = 1024 * 1024
NIGHT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CSV_HEADER = "time_local,epoch,temp_c,rh_pct"
TEST_NIGHT = "1999-12-31"
ALLOWED_NETS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
]


def is_allowed_client(addr: str) -> bool:
    """True for private-LAN and loopback addresses."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in ALLOWED_NETS)


def token_ok(given: str | None, expected: str) -> bool:
    """Constant-time token check; an empty expected token never matches."""
    return bool(expected) and given is not None and hmac.compare_digest(given, expected)


def validate_upload(night: str | None, body: bytes) -> str | None:
    """Return an error message, or None when the upload is acceptable."""
    if night is None or not NIGHT_RE.match(night):
        return "bad or missing X-Night (want YYYY-MM-DD)"
    if not body:
        return "empty body"
    if not body.decode("utf-8", errors="replace").startswith(CSV_HEADER):
        return f"body must start with header {CSV_HEADER!r}"
    return None


def dest_name(night: str, now: float) -> str:
    """File name for one night: arrival timestamp first, so a re-upload never overwrites."""
    return f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}_night-{night}.csv"


def write_atomically(dest: Path, body: bytes) -> None:
    """Write via a .part file so a crash never leaves a truncated CSV under the final name."""
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(body)
    os.replace(part, dest)


def local_name() -> str:
    """This computer's mDNS name, lowercased, without .local (macOS LocalHostName, else hostname).

    mDNS names are case-insensitive; the sensor is given the lowercase form.
    """
    return _raw_local_name().lower()


def _raw_local_name() -> str:
    """The name as the system reports it."""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["scutil", "--get", "LocalHostName"],
                capture_output=True,
                text=True,
                check=True,
            )
            if out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return socket.gethostname().split(".")[0]


def lan_address() -> str:
    """The address this computer uses on its network, or '' (sends no packets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address: only picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return ""


def macos_firewall_python() -> str:
    """One check line on whether the macOS firewall lets Python accept connections, or ''."""
    tool = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    if sys.platform != "darwin" or not os.path.exists(tool):
        return ""
    try:
        state = subprocess.run([tool, "--getglobalstate"], capture_output=True, text=True).stdout
    except OSError:
        return ""
    if "enabled" not in state.lower():
        return "ok      macOS firewall is off"
    candidates = [
        Path(sys.base_prefix) / "Resources" / "Python.app",
        Path(sys.executable).resolve(),
    ]
    for app in candidates:
        if not app.exists():
            continue
        try:
            out = subprocess.run(
                [tool, "--getappblocked", str(app)], capture_output=True, text=True
            ).stdout.lower()
        except OSError:
            break
        if "permitted" in out:
            return "ok      macOS firewall is on and lets Python accept connections"
        if "blocked" in out:
            return (
                "MISSING macOS firewall blocks Python: System Settings, Network, Firewall, "
                "Options, set Python to Allow incoming connections"
            )
    return (
        "WARN    macOS firewall is on and Python is not listed yet: when macOS asks whether "
        "Python may accept incoming connections, choose Allow"
    )


def read_token(path: Path) -> str:
    """Return the token in path, or '' when it is missing or unreadable."""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


class Handler(BaseHTTPRequestHandler):
    """GET /health, GET /bedside/hello?..., POST /bedside/temp."""

    server_version = "bedside-receiver/1"

    def _reply(self, code: int, text: str) -> None:
        data = (text + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._reply(200, "ok")
        elif path == "/bedside/hello":
            # The request line (with the sensor's state in the query) is the log entry.
            if not is_allowed_client(self.client_address[0]):
                self._reply(403, "forbidden network")
            else:
                self._reply(200, "ok")
        else:
            self._reply(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        if not is_allowed_client(self.client_address[0]):
            self._reply(403, "forbidden network")
            return
        if self.path != "/bedside/temp":
            self._reply(404, "not found")
            return
        if not token_ok(self.headers.get("X-Token"), self.server.token):  # type: ignore[attr-defined]
            self._reply(401, "bad token")
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._reply(400, "bad Content-Length")
            return
        body = self.rfile.read(length)
        night = self.headers.get("X-Night")
        error = validate_upload(night, body)
        if error:
            self._reply(400, error)
            return
        out_dir: Path = self.server.out_dir  # type: ignore[attr-defined]
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / dest_name(night, time.time())  # type: ignore[arg-type]
        write_atomically(dest, body)
        self.log_message("saved %s (%d bytes)", dest.name, len(body))
        self._reply(200, dest.name)


def make_server(port: int, token: str, out_dir: Path, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Build (not start) the HTTP server."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.token = token  # type: ignore[attr-defined]
    server.out_dir = out_dir  # type: ignore[attr-defined]
    return server


def make_token(path: Path) -> int:
    """Create the token file (mode 600) unless one exists. Never prints the token."""
    if read_token(path):
        print(f"ok token already exists at {path} (kept)")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_hex(16) + "\n")
    os.chmod(path, 0o600)
    print(f"ok token created at {path} (not shown)")
    return 0


def _get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    """GET url; return (status, body), or (0, reason) when nothing answered."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode().strip()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode().strip()
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc))


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float = 5.0) -> tuple[int, str]:
    """POST body to url; return (status, body), or (0, reason) when nothing answered."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode().strip()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode().strip()
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc))


def check(port: int, token_file: Path, out_dir: Path) -> int:
    """Print one line per readiness item; return 1 if anything is MISSING."""
    missing = 0
    token = read_token(token_file)
    if token:
        print(f"ok      token file {token_file}")
    else:
        print(
            f"MISSING token file {token_file}: "
            "run  python3 receiver/bedside_receiver.py --make-token"
        )
        missing += 1
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".write-test"
        probe.write_text("x")
        probe.unlink()
        print(f"ok      nights folder {out_dir}")
    except OSError as exc:
        print(f"MISSING nights folder {out_dir} is not writable: {exc}")
        missing += 1
    status, body = _get(f"http://127.0.0.1:{port}/health")
    if status == 200 and body == "ok":
        print(f"ok      receiver answering on port {port}")
    else:
        print(f"MISSING receiver not answering on port {port} ({body or status}): start it")
        missing += 1
    name = local_name()
    try:
        socket.gethostbyname(f"{name}.local")
        print(
            f"ok      the sensor will look for {name}.local (resolves here; whether other devices "
            "can find it shows at the first flash)"
        )
    except OSError:
        print(
            f"WARN    {name}.local does not resolve on this computer. The sensor may still find it "
            "if mDNS is running (Linux: avahi-daemon); if not, use a fixed address (RECEIVER_IP)."
        )
    firewall = macos_firewall_python()
    if firewall:
        print(firewall)
        if firewall.startswith("MISSING"):
            missing += 1
    lan = lan_address()
    if lan and is_allowed_client(lan) and not lan.startswith("127."):
        print(f"ok      this computer's LAN address is {lan} (for RECEIVER_IP, if ever needed)")
    else:
        print(
            f"WARN    no private LAN address found ({lan or 'none'}): "
            "is this computer on the network?"
        )
    return 1 if missing else 0


def test_upload(port: int, token_file: Path, out_dir: Path) -> int:
    """Exercise the running receiver the way the sensor does; delete the test file after."""
    token = read_token(token_file)
    if not token:
        print(f"MISSING token file {token_file}: run --make-token first")
        return 1
    base = f"http://127.0.0.1:{port}"
    status, _ = _get(
        f"{base}/bedside/hello?fw=test&reset=1&rows=0&fails=0&code=0&rssi=0&readfail=0"
    )
    if status != 200:
        print(
            f"FAIL    hello check-in got {status or 'no answer'}: "
            f"is the receiver running on {port}?"
        )
        return 1
    body = (
        f"{CSV_HEADER}\n"
        "1999-12-31T21:30:00,946697400,21.40,48.20\n"
        "1999-12-31T21:30:30,946697430,21.41,48.10\n"
    ).encode()
    headers = {"Content-Type": "text/csv", "X-Night": TEST_NIGHT}
    status, _ = _post(f"{base}/bedside/temp", body, {**headers, "X-Token": "wrong-token"})
    if status != 401:
        print(f"FAIL    a wrong token got {status}, expected 401")
        return 1
    status, name = _post(f"{base}/bedside/temp", body, {**headers, "X-Token": token})
    if status != 200:
        print(f"FAIL    test upload got {status}: {name}")
        return 1
    saved = out_dir / name
    if not saved.is_file():
        print(
            f"FAIL    receiver saved {name}, but it is not in {out_dir} "
            "(started with another --out?)"
        )
        return 1
    same = saved.read_bytes() == body
    saved.unlink()
    if not same:
        print(f"FAIL    {name} does not match what was sent")
        return 1
    print(f"ok      hello check-in 200; wrong token refused 401; test night saved as {name},")
    print("        identical to what was sent, then deleted")
    return 0


def serve(port: int, token_file: Path, out_dir: Path) -> int:
    """Serve forever; return non-zero when it cannot start."""
    token = read_token(token_file)
    if not token:
        print(
            f"bedside_receiver: no token at {token_file}; run with --make-token first",
            file=sys.stderr,
        )
        return 1
    try:
        server = make_server(port, token, out_dir)
    except OSError as exc:
        print(
            f"bedside_receiver: cannot listen on port {port} ({exc}). Already running? "
            f"curl http://127.0.0.1:{port}/health",
            file=sys.stderr,
        )
        return 1
    print(
        f"bedside_receiver: listening on :{port}, saving nights to {out_dir}, "
        f"sensor should look for {local_name()}.local",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run one mode."""
    p = argparse.ArgumentParser(description="Receiver for the bedside temperature sensor.")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the night files")
    p.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--make-token", action="store_true", help="create the token file")
    mode.add_argument("--check", action="store_true", help="is everything ready?")
    mode.add_argument(
        "--test-upload", action="store_true", help="fake upload to the running receiver"
    )
    mode.add_argument("--print-name", action="store_true", help="name the sensor should look for")
    a = p.parse_args(argv)
    out = a.out.expanduser()
    token_file = a.token_file.expanduser()
    if a.make_token:
        return make_token(token_file)
    if a.check:
        return check(a.port, token_file, out)
    if a.test_upload:
        return test_upload(a.port, token_file, out)
    if a.print_name:
        print(local_name())
        return 0
    return serve(a.port, token_file, out)


if __name__ == "__main__":
    sys.exit(main())
