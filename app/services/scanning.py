"""Malware scanning of uploads with ClamAV's clamd, over TCP.

The INSTREAM command (https://docs.clamav.net/manual/Usage/Scanning.html): send
"zINSTREAM\\0", then the file in chunks, each one after its length as a 4-byte
big-endian number, then a zero length. clamd answers with one line ending in a
NUL byte: "stream: OK", "stream: <signature> FOUND" or "<reason> ERROR".

When scanning is on and clamd can't be reached or gives any other answer, the
upload is refused: the scanner fails closed.
"""

import re
import socket
import struct
from dataclasses import dataclass
from typing import Protocol

# clamd's default StreamMaxLength is 25 MB, well above the upload limit.
_CHUNK_BYTES = 64 * 1024
_MAX_REPLY_BYTES = 4096
# What a signature name or an error from clamd may hold before it goes in a log line.
_SIGNATURE_RE = re.compile(r"[^A-Za-z0-9._:/-]")
_TEXT_RE = re.compile(r"[^A-Za-z0-9 ._:/-]")


class ScannerUnavailable(Exception):
    """clamd couldn't be reached or didn't give a usable answer. The message
    describes the problem and never holds file contents."""


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class Scanner(Protocol):
    def scan(self, data: bytes) -> ScanResult: ...

    def ping(self) -> None:
        """Raise ScannerUnavailable unless the scanner answers."""


def parse_reply(reply: bytes) -> ScanResult:
    text = reply.rstrip(b"\0").decode("utf-8", errors="replace").strip()
    # "stream: OK"; older clamd versions answer "1: stream: OK" in session mode.
    body = text.split("stream:", 1)[1].strip() if "stream:" in text else text
    if body == "OK":
        return ScanResult(clean=True)
    if body.endswith(" FOUND"):
        signature = body[: -len(" FOUND")].strip()
        return ScanResult(clean=False, signature=_SIGNATURE_RE.sub("_", signature)[:200])
    raise ScannerUnavailable(f"clamd answered: {_TEXT_RE.sub('_', text)[:200]}")


class ClamAVScanner:
    def __init__(self, host: str, port: int, *, timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def _connect(self) -> socket.socket:
        try:
            return socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise ScannerUnavailable(
                f"can't connect to clamd at {self.host}:{self.port}: {type(exc).__name__}"
            ) from None

    @staticmethod
    def _read_reply(sock: socket.socket) -> bytes:
        reply = b""
        while not reply.endswith(b"\0") and len(reply) < _MAX_REPLY_BYTES:
            chunk = sock.recv(_MAX_REPLY_BYTES)
            if not chunk:
                break
            reply += chunk
        if not reply:
            raise ScannerUnavailable("clamd closed the connection without an answer")
        return reply

    def scan(self, data: bytes) -> ScanResult:
        with self._connect() as sock:
            try:
                sock.sendall(b"zINSTREAM\0")
                for start in range(0, len(data), _CHUNK_BYTES):
                    chunk = data[start : start + _CHUNK_BYTES]
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                sock.sendall(struct.pack("!I", 0))
            except OSError as exc:
                # clamd stops reading and answers early when a stream is too long.
                try:
                    return parse_reply(self._read_reply(sock))
                except (OSError, ScannerUnavailable):
                    raise ScannerUnavailable(
                        f"clamd stopped reading the file: {type(exc).__name__}"
                    ) from None
            try:
                reply = self._read_reply(sock)
            except OSError as exc:
                raise ScannerUnavailable(f"no answer from clamd: {type(exc).__name__}") from None
        return parse_reply(reply)

    def ping(self) -> None:
        with self._connect() as sock:
            try:
                sock.sendall(b"zPING\0")
                reply = self._read_reply(sock)
            except OSError as exc:
                raise ScannerUnavailable(f"no answer from clamd: {type(exc).__name__}") from None
        if reply.rstrip(b"\0").strip() != b"PONG":
            raise ScannerUnavailable("clamd didn't answer PING with PONG")
