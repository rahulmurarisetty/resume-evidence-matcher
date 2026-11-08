"""The clamd client against a fake clamd on a local port."""

import pytest

from app.services.scanning import ClamAVScanner, ScannerUnavailable, ScanResult, parse_reply
from tests.fake_clamd import EICAR, closed_port, fake_clamd


def _scanner(port: int, timeout: float = 5.0) -> ClamAVScanner:
    return ClamAVScanner("127.0.0.1", port, timeout=timeout)


def test_eicar_is_assembled_at_runtime() -> None:
    assert len(EICAR) == 68 and EICAR.startswith(b"X5O!") and EICAR.endswith(b"H+H*")


def test_clean_file_and_chunk_framing() -> None:
    data = b"%PDF-1.7\n" + b"a" * 150_000
    with fake_clamd() as clamd:
        assert _scanner(clamd.port).scan(data) == ScanResult(clean=True)
    assert clamd.received.commands == [b"zINSTREAM"]
    assert clamd.received.streams == [data]
    # 64 KiB chunks, the last one shorter.
    assert clamd.received.chunk_sizes == [65536, 65536, len(data) - 131072]


def test_empty_stream() -> None:
    with fake_clamd() as clamd:
        assert _scanner(clamd.port).scan(b"").clean
    assert clamd.received.chunk_sizes == []


def test_infected_file() -> None:
    with fake_clamd() as clamd:
        result = _scanner(clamd.port).scan(b"%PDF-1.7\n" + EICAR + b"\n%%EOF")
    assert result == ScanResult(clean=False, signature="Eicar-Test-Signature")


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("error", "size limit exceeded"),
        ("close", "without an answer"),
        ("garbage", "something odd"),
    ],
)
def test_other_answers_fail_closed(mode: str, message: str) -> None:
    with fake_clamd(mode) as clamd, pytest.raises(ScannerUnavailable, match=message):
        _scanner(clamd.port).scan(b"data")


def test_clamd_hanging_up_mid_stream_fails_closed() -> None:
    # Bigger than the socket buffers, so sending fails once clamd stops reading.
    with fake_clamd("limit") as clamd, pytest.raises(ScannerUnavailable):
        _scanner(clamd.port).scan(b"x" * (16 * 1024 * 1024))


def test_timeout_fails_closed() -> None:
    with fake_clamd("silent") as clamd, pytest.raises(ScannerUnavailable, match="TimeoutError"):
        _scanner(clamd.port, timeout=0.2).scan(b"data")


def test_unreachable_fails_closed() -> None:
    with pytest.raises(ScannerUnavailable, match=r"can't connect to clamd at 127\.0\.0\.1"):
        _scanner(closed_port(), timeout=1).scan(b"data")


def test_ping() -> None:
    with fake_clamd() as clamd:
        _scanner(clamd.port).ping()
    assert clamd.received.commands == [b"zPING"]
    with fake_clamd("bad-pong") as clamd, pytest.raises(ScannerUnavailable, match="PONG"):
        _scanner(clamd.port).ping()
    with pytest.raises(ScannerUnavailable):
        _scanner(closed_port(), timeout=1).ping()


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (b"stream: OK\0", ScanResult(clean=True)),
        (b"1: stream: OK\0", ScanResult(clean=True)),
        (b"stream: Win.Test.EICAR_HDB-1 FOUND\0", ScanResult(False, "Win.Test.EICAR_HDB-1")),
        # A signature name is cleaned before it can reach a log line.
        (b'stream: Bad"Name\n{x} FOUND\0', ScanResult(False, "Bad_Name__x_")),
    ],
)
def test_parse_reply(reply: bytes, expected: ScanResult) -> None:
    assert parse_reply(reply) == expected


def test_parse_reply_errors() -> None:
    with pytest.raises(ScannerUnavailable, match="ERROR"):
        parse_reply(b"Can't allocate memory ERROR\0")
