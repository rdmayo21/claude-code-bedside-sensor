from __future__ import annotations

import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from bedside_receiver import (  # noqa: E402
    dest_name,
    is_allowed_client,
    make_server,
    make_token,
    read_token,
    token_ok,
    validate_upload,
    write_atomically,
)

GOOD_BODY = b"time_local,epoch,temp_c,rh_pct\n2026-10-05T02:00:00,1791190800,21.40,52.10\n"


def test_lan_and_loopback_clients_are_allowed() -> None:
    assert is_allowed_client("10.1.2.3")
    assert is_allowed_client("172.16.4.2")
    assert is_allowed_client("192.168.1.5")
    assert is_allowed_client("127.0.0.1")


def test_public_and_garbage_clients_are_refused() -> None:
    assert not is_allowed_client("8.8.8.8")
    assert not is_allowed_client("not-an-ip")


def test_token_must_match_exactly() -> None:
    assert token_ok("abc123", "abc123")
    assert not token_ok("abc124", "abc123")
    assert not token_ok(None, "abc123")


def test_empty_expected_token_never_matches() -> None:
    assert not token_ok("", "")


def test_valid_upload_passes() -> None:
    assert validate_upload("2026-10-04", GOOD_BODY) is None


def test_bad_night_is_rejected() -> None:
    assert validate_upload("2026-10-4", GOOD_BODY) is not None
    assert validate_upload("../etc", GOOD_BODY) is not None
    assert validate_upload(None, GOOD_BODY) is not None


def test_body_without_header_is_rejected() -> None:
    assert validate_upload("2026-10-04", b"hello") is not None
    assert validate_upload("2026-10-04", b"") is not None


def test_dest_name_is_timestamp_then_night() -> None:
    name = dest_name("2026-10-04", 0.0)
    assert name.endswith("_night-2026-10-04.csv")
    assert len(name.split("_")[0]) == 15  # YYYYMMDD-HHMMSS


def test_write_atomically_leaves_no_part_file(tmp_path: Path) -> None:
    dest = tmp_path / "x.csv"
    write_atomically(dest, GOOD_BODY)
    assert dest.read_bytes() == GOOD_BODY
    assert not (tmp_path / "x.csv.part").exists()


def test_make_token_creates_private_file_and_keeps_it(tmp_path: Path, capsys) -> None:
    path = tmp_path / "cfg" / "token"
    make_token(path)
    token = read_token(path)
    assert len(token) == 32
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert token not in capsys.readouterr().out
    make_token(path)
    assert read_token(path) == token


@pytest.fixture()
def server(tmp_path: Path):
    srv = make_server(0, "secret-token", tmp_path / "nights", host="127.0.0.1")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "nights"
    srv.shutdown()
    srv.server_close()


def _request(url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode().strip()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode().strip()


def test_upload_end_to_end_saves_identical_bytes(server) -> None:
    base, out = server
    headers = {
        "X-Token": "secret-token",
        "X-Night": "2026-10-04",
        "Content-Type": "text/csv",
    }
    status, name = _request(f"{base}/bedside/temp", GOOD_BODY, headers)
    assert status == 200
    assert name.endswith("_night-2026-10-04.csv")
    assert (out / name).read_bytes() == GOOD_BODY


def test_upload_with_wrong_token_is_refused_and_saves_nothing(server) -> None:
    base, out = server
    headers = {"X-Token": "nope", "X-Night": "2026-10-04"}
    assert _request(f"{base}/bedside/temp", GOOD_BODY, headers)[0] == 401
    assert not out.exists() or not any(out.iterdir())


def test_upload_with_bad_night_is_refused(server) -> None:
    base, _ = server
    headers = {"X-Token": "secret-token", "X-Night": "../../x"}
    assert _request(f"{base}/bedside/temp", GOOD_BODY, headers)[0] == 400


def test_health_and_hello_answer(server) -> None:
    base, _ = server
    assert _request(f"{base}/health") == (200, "ok")
    assert _request(f"{base}/bedside/hello?fw=1.0.0&reset=1")[0] == 200
    assert _request(f"{base}/other")[0] == 404
