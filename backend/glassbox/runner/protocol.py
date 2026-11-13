"""Protocol channel (NDJSON over a duplicated copy of the real stdout fd) and fd capture."""

from __future__ import annotations

import codecs
import io
import os
import threading
from collections.abc import Callable
from typing import Any

# A private copy of the real stderr (the parent's pipe). Only used to report a failure of the runner itself.
real_stderr_fd = -1

FLUSH_BYTES = 64 * 1024
FLUSH_INTERVAL_S = 0.05


def open_channel(cap_dir: str) -> tuple[int, str, str]:
    """Duplicate the real stdout as the protocol fd, then point fd 1 and 2 at capture files.

    After this, anything user code writes to fd 1/2 (even via os.write) lands in the capture files and
    can never corrupt the protocol stream.
    """
    global real_stderr_fd
    real_stderr_fd = os.dup(2)
    proto_fd = os.dup(1)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    paths = []
    for fd, name in ((1, "stdout.cap"), (2, "stderr.cap")):
        path = os.path.join(cap_dir, name)
        f = os.open(path, flags)
        os.dup2(f, fd)
        os.close(f)
        paths.append(path)
    return proto_fd, paths[0], paths[1]


class ProtocolWriter:
    """Buffers NDJSON lines and flushes by size, by a background timer, and on demand."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._buf: list[bytes] = []
        self._size = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def write_line(self, line: str) -> None:
        data = line.encode("ascii") + b"\n"
        with self._lock:
            self._buf.append(data)
            self._size += len(data)
            if self._size >= FLUSH_BYTES:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buf:
            return
        data = b"".join(self._buf)
        self._buf.clear()
        self._size = 0
        try:
            view = memoryview(data)
            while view:
                n = os.write(self._fd, view)
                view = view[n:]
        except OSError:
            # The parent closed the pipe: nobody is listening, stop immediately.
            os._exit(1)

    def start_flusher(self) -> None:
        """Flush every 50 ms from a helper thread so events stream live and survive a hang in C code."""

        def loop() -> None:
            while not self._stop.wait(FLUSH_INTERVAL_S):
                self.flush()

        self._thread = threading.Thread(target=loop, name="glassbox-flusher", daemon=True)
        self._thread.start()

    def stop_flusher(self) -> None:
        self._stop.set()


class _Buffer:
    """Minimal ``sys.stdout.buffer`` replacement (bytes in, decoded text out)."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def write(self, data: Any) -> int:
        raw = bytes(data)
        self._sink(raw.decode("utf-8", "replace"))
        return len(raw)

    def flush(self) -> None:
        return None


class OutStream(io.TextIOBase):
    """Replaces sys.stdout / sys.stderr: every write becomes an `output` event with the current step."""

    def __init__(self, stream: str, sink: Callable[[str, str], None]) -> None:
        super().__init__()
        self._stream = stream
        self._emit = sink
        self.buffer = _Buffer(self._write_text)  # type: ignore[assignment]

    def _write_text(self, text: str) -> None:
        self._emit(self._stream, text)

    def write(self, s: str) -> int:
        self._emit(self._stream, s)
        return len(s)

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def flush(self) -> None:
        return None

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"


class FdCapture:
    """Incrementally reads text that was written to a captured fd (via its capture file)."""

    def __init__(self, path: str) -> None:
        self._file = open(path, "rb")  # noqa: SIM115 - kept open for the whole run
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def poll(self, final: bool = False) -> str:
        return self._decoder.decode(self._file.read(), final)

    def close(self) -> None:
        self._file.close()
