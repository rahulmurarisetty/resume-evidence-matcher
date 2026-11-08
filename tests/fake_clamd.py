"""A stand-in for clamd on a local port, speaking the INSTREAM protocol.

It answers "stream: OK", or "stream: Eicar-Test-Signature FOUND" when the stream
holds the EICAR test string, and can be told to misbehave. The EICAR string is
put together at runtime, so no file in this repository holds it and a virus
scanner on a developer's machine has nothing to flag.
"""

import socket
import socketserver
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

# The standard antivirus test file, reversed in the source.
EICAR = "*H+H$!ELIF-TSET-SURIVITNA-DRADNATS-RACIE$}7)CC7)^P(45XZP\\4[PA@%P!O5X"[::-1].encode()

MODES = ("scan", "error", "close", "silent", "garbage", "bad-pong", "limit")


@dataclass
class Received:
    commands: list[bytes] = field(default_factory=list)
    chunk_sizes: list[int] = field(default_factory=list)
    streams: list[bytes] = field(default_factory=list)


def _read_exact(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def _read_command(conn: socket.socket) -> bytes:
    command = b""
    while not command.endswith(b"\0"):
        command += _read_exact(conn, 1)
    return command[:-1]


class FakeClamd:
    def __init__(self, mode: str = "scan") -> None:
        assert mode in MODES
        self.mode = mode
        self.received = Received()
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                fake._handle(self.request)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handle(self, conn: socket.socket) -> None:
        try:
            command = _read_command(conn)
        except ConnectionError:
            return
        self.received.commands.append(command)
        if command == b"zPING":
            conn.sendall(b"PONG\0" if self.mode != "bad-pong" else b"PANG\0")
            return
        if command != b"zINSTREAM":
            conn.sendall(b"UNKNOWN COMMAND\0")
            return
        stream = b""
        try:
            while True:
                (size,) = struct.unpack("!I", _read_exact(conn, 4))
                if size == 0:
                    break
                self.received.chunk_sizes.append(size)
                stream += _read_exact(conn, size)
                if self.mode == "limit":
                    # As clamd does past StreamMaxLength: answer at once and hang up.
                    conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                    conn.shutdown(socket.SHUT_RDWR)
                    return
        except ConnectionError:
            return
        self.received.streams.append(stream)
        if self.mode == "error":
            conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
        elif self.mode == "close":
            return
        elif self.mode == "silent":
            time.sleep(1.0)
        elif self.mode == "garbage":
            conn.sendall(b"stream: something odd\0")
        elif EICAR in stream:
            conn.sendall(b"stream: Eicar-Test-Signature FOUND\0")
        else:
            conn.sendall(b"stream: OK\0")

    def start(self) -> "FakeClamd":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@contextmanager
def fake_clamd(mode: str = "scan") -> Iterator[FakeClamd]:
    server = FakeClamd(mode).start()
    try:
        yield server
    finally:
        server.stop()


def closed_port() -> int:
    """A local port with nothing listening on it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port
