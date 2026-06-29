"""
whisper.cpp backend.

Spawns a ``whisper-server`` binary (built with ``-DGGML_VULKAN=1``)
on a free localhost port, keeps it alive for the lifetime of the
backend, and POSTs WAV-encoded audio to ``/inference`` per
transcription.

The Vulkan-built binary works on AMD, NVIDIA, and Intel GPUs without
vendor SDKs (the Vulkan loader ships with modern GPU drivers).  If the
binary fails to start because no Vulkan device is present, ``load()``
raises and ``DictateApp`` falls back to the CPU backend.

GGUF model files (``ggml-*.bin``) are downloaded on first use to:
  - Windows: ``%LOCALAPPDATA%\\Auritus\\models\\``
  - Linux:   ``~/.local/share/Auritus/models/``

Both backends can coexist and share nothing.

Linux binary resolution order:
  1. ``WHISPER_CPP_SERVER`` env var (absolute path to whisper-server)
  2. ``whisper-server`` on PATH (``shutil.which``)
  3. Raises RuntimeError with install instructions.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from .base import Backend, LogFn


# Auritus model name -> whisper.cpp GGUF filename.
MODEL_FILE_MAP: dict[str, str] = {
    "tiny.en":   "ggml-tiny.en.bin",
    "base.en":   "ggml-base.en.bin",
    "small.en":  "ggml-small.en.bin",
    "medium.en": "ggml-medium.en.bin",
    "large-v3":  "ggml-large-v3.bin",
}

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"

# Server boot watchdog.  Vulkan device enumeration + model load on
# medium.en takes ~5-15 s on a typical AMD GPU.  Larger models on slower
# machines need more headroom.
SERVER_BOOT_TIMEOUT_S = 60.0

# Maximum bytes of whisper-server stdout+stderr to retain in memory for
# crash diagnostics.  Drainer threads truncate the ring buffer to this
# size; without active draining the OS pipe buffer (~4-64 KB on Windows)
# fills after a few inferences and the server deadlocks on its next
# write.
SERVER_LOG_TAIL_BYTES = 16 * 1024


# ----------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------

def _vendor_dir() -> Path:
    """Return the directory that holds whisper-server.exe and its DLLs (Windows only).

    In the PyInstaller bundle the binaries are unpacked under
    ``sys._MEIPASS/vendor/whisper-cpp/``.  In a dev checkout they live
    in ``vendor/whisper-cpp/`` next to ``dictate.py``.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        # backends/whisper_cpp_backend.py -> repo root
        base = Path(__file__).resolve().parent.parent
    return base / "vendor" / "whisper-cpp"


def _server_path() -> Path:
    """Resolve the whisper-server binary path for the current platform.

    Windows: bundled ``vendor/whisper-cpp/whisper-server.exe``.
    Linux:   ``WHISPER_CPP_SERVER`` env var, else ``whisper-server`` on PATH.
    """
    if sys.platform == "win32":
        return _vendor_dir() / "whisper-server.exe"
    # Linux / macOS
    env_path = os.environ.get("WHISPER_CPP_SERVER")
    if env_path:
        return Path(env_path)
    which = shutil.which("whisper-server")
    if which:
        return Path(which)
    raise RuntimeError(
        "whisper-server not found. Build whisper.cpp with -DGGML_VULKAN=ON, "
        "then set WHISPER_CPP_SERVER=/path/to/build/bin/whisper-server "
        "or add it to PATH."
    )


def _models_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(appdata) / "Auritus" / "models"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        p = Path(xdg) / "Auritus" / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _free_localhost_port() -> int:
    """Ask the OS for a free TCP port, then immediately release it.

    Tiny race window between bind/close and the server's bind, but in
    practice this is the standard trick for picking an ephemeral port
    and is good enough for a single-user desktop app.
    """
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


# ----------------------------------------------------------------------
# Backend
# ----------------------------------------------------------------------

class WhisperCppBackend(Backend):
    name = "gpu"
    label = "GPU (whisper.cpp Vulkan)"

    def __init__(self, log: LogFn | None = None) -> None:
        self._log = log or (lambda _msg: None)
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.model_name: str | None = None
        self._stderr_tail: str = ""
        self._tail_lock = threading.Lock()
        self._drain_threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def available(cls) -> tuple[bool, str]:
        try:
            srv = _server_path()
        except RuntimeError as e:
            return False, str(e)
        if not srv.exists():
            name = "whisper-server.exe" if sys.platform == "win32" else "whisper-server"
            return False, f"{name} missing (expected at {srv})"
        return True, ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _ensure_model_file(self, model_name: str) -> Path:
        fname = MODEL_FILE_MAP.get(model_name)
        if fname is None:
            raise ValueError(f"WhisperCppBackend: unsupported model {model_name!r}")
        path = _models_dir() / fname
        if path.exists() and path.stat().st_size > 0:
            return path

        url = HF_BASE + fname
        self._log(f"[backend:gpu] Downloading {fname} from HuggingFace ...")
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            tmp.replace(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        self._log(f"[backend:gpu] Saved model to {path}")
        return path

    def load(self, model_name: str) -> None:
        # Always start clean -- whisper-server has no /load endpoint, so
        # swapping models means restarting the process.
        self.unload()

        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"WhisperCppBackend not available: {reason}")

        model_path = self._ensure_model_file(model_name)
        port = _free_localhost_port()
        cmd = [
            str(_server_path()),
            "--model",      str(model_path),
            "--host",       "127.0.0.1",
            "--port",       str(port),
            "--no-timestamps",
            "--threads",    "4",
        ]
        self._log(f"[backend:gpu] Spawning whisper-server on :{port} with {model_name}")

        creationflags = 0
        # cwd is the vendor dir on Windows so the loader finds sibling DLLs.
        # On Linux the binary is standalone; cwd doesn't matter.
        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # CREATE_NO_WINDOW: keep the server console hidden when Auritus
            # itself runs under pythonw / a windowed PyInstaller bundle.
            popen_kwargs["creationflags"] = 0x08000000
            popen_kwargs["cwd"] = str(_vendor_dir())

        try:
            self.proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError as e:
            raise RuntimeError(f"whisper-server failed to launch: {e}") from e

        self.port = port

        # Start drainer threads BEFORE waiting for ready.  whisper-server
        # writes Vulkan device + model-load progress to stderr during
        # boot; if we don't drain, even startup can deadlock on larger
        # models / slower disks.
        with self._tail_lock:
            self._stderr_tail = ""
        self._drain_threads = []
        if self.proc.stdout is not None:
            self._start_drainer(self.proc.stdout, "stdout")
        if self.proc.stderr is not None:
            self._start_drainer(self.proc.stderr, "stderr")

        try:
            self._wait_ready()
        except Exception:
            self.unload()
            raise

        self.model_name = model_name
        self._log(f"[backend:gpu] whisper-server ready on :{port}")

    def _start_drainer(self, stream, label: str) -> None:
        """Pump a subprocess pipe into the bounded tail buffer.

        Without this, the OS pipe buffer fills after a few inferences
        and whisper-server blocks on its next ``fwrite``, which in turn
        stalls the next ``/inference`` HTTP request.
        """
        def _pump() -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", "replace")
                    with self._tail_lock:
                        self._stderr_tail += text
                        if len(self._stderr_tail) > SERVER_LOG_TAIL_BYTES:
                            self._stderr_tail = self._stderr_tail[-SERVER_LOG_TAIL_BYTES:]
            except Exception:
                pass

        t = threading.Thread(target=_pump, name=f"whisper-srv-{label}", daemon=True)
        t.start()
        self._drain_threads.append(t)

    def _wait_ready(self) -> None:
        """Poll the server's HTTP root until it responds, with a hard cap."""
        if self.proc is None or self.port is None:
            raise RuntimeError("whisper-server: no process to wait on")

        deadline = time.time() + SERVER_BOOT_TIMEOUT_S
        url = f"http://127.0.0.1:{self.port}/"

        while time.time() < deadline:
            # Did the server die while we were waiting?
            rc = self.proc.poll()
            if rc is not None:
                err = self._read_stderr_tail()
                raise RuntimeError(
                    f"whisper-server exited with code {rc} during startup. "
                    f"Tail: {err[-400:] if err else '(empty)'}"
                )

            try:
                with urllib.request.urlopen(url, timeout=0.5) as resp:
                    # Any response (200 or 404 from a route we didn't ask for)
                    # means the HTTP listener is up.
                    resp.read()
                    return
            except urllib.error.URLError:
                time.sleep(0.25)

        err = self._read_stderr_tail()
        raise TimeoutError(
            f"whisper-server did not become ready in {SERVER_BOOT_TIMEOUT_S:.0f}s. "
            f"Tail: {err[-400:] if err else '(empty)'}"
        )

    def _read_stderr_tail(self) -> str:
        """Return the current bounded stdout+stderr tail.

        A pair of daemon drainer threads continuously pump the pipes
        into ``self._stderr_tail`` (capped at ``SERVER_LOG_TAIL_BYTES``)
        so this call never blocks and never touches the pipe directly.
        """
        with self._tail_lock:
            return self._stderr_tail

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def transcribe(self, audio: np.ndarray) -> str:
        if self.proc is None or self.port is None:
            raise RuntimeError("WhisperCppBackend.transcribe called before load()")
        if self.proc.poll() is not None:
            raise RuntimeError(
                f"whisper-server died (exit {self.proc.returncode}). "
                f"Tail: {self._read_stderr_tail()[-400:]}"
            )

        # whisper.cpp expects 16-bit PCM WAV at 16 kHz mono.  scipy's
        # wavfile is part of the existing dep set, so use it instead of
        # pulling in soundfile.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        pcm16 = np.clip(audio * 32768.0, -32768.0, 32767.0).astype(np.int16)
        buf = io.BytesIO()
        wavfile.write(buf, 16000, pcm16)
        wav_bytes = buf.getvalue()

        body, content_type = _build_multipart(
            wav_bytes,
            language="en" if self.model_name and self.model_name.endswith(".en") else "auto",
        )

        # whisper-server occasionally resets the connection on a single
        # request while the process itself stays alive (a handler crash, not
        # a full death). The captured audio is irreplaceable, so retry once
        # before giving up; the next attempt almost always succeeds. The
        # server's stderr tail is logged on each failure so the underlying
        # cause is finally visible instead of just "connection reset".
        transient = (ConnectionResetError, http.client.RemoteDisconnected)
        last_exc: BaseException | None = None
        for attempt in range(2):
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"whisper-server died (exit {self.proc.returncode}). "
                    f"Tail: {self._read_stderr_tail()[-400:]}"
                )
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/inference",
                data=body,
                headers={"Content-Type": content_type},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=3600) as resp:
                    payload = resp.read().decode("utf-8", "replace")
                try:
                    return json.loads(payload).get("text", "").strip()
                except json.JSONDecodeError:
                    return payload.strip()
            except urllib.error.URLError as e:
                # URLError wraps the socket reset in .reason; HTTPError (a
                # subclass) carries a real HTTP status and is not transient.
                last_exc = e
                is_reset = not isinstance(e, urllib.error.HTTPError) and (
                    isinstance(getattr(e, "reason", None), transient)
                )
            except transient as e:
                last_exc = e
                is_reset = True

            self._log(
                f"[backend:gpu] /inference attempt {attempt + 1} failed: "
                f"{last_exc}. Tail: {self._read_stderr_tail()[-400:]}"
            )
            if not (is_reset and attempt == 0):
                break
            time.sleep(0.25)

        raise RuntimeError(f"whisper-server /inference failed: {last_exc}")

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def unload(self) -> None:
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        try:
                            self.proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                # Pipes close once the child exits; give the drainer
                # threads a brief moment to flush the final bytes into
                # the tail buffer so crash logs are complete.
                for t in self._drain_threads:
                    t.join(timeout=1.0)
            except Exception as e:
                self._log(f"[backend:gpu] unload error: {e}")
            finally:
                self.proc = None
        self._drain_threads = []
        self.port = None
        self.model_name = None


# ----------------------------------------------------------------------
# Multipart helper
# ----------------------------------------------------------------------

def _build_multipart(wav_bytes: bytes, *, language: str) -> tuple[bytes, str]:
    """Hand-rolled multipart so we don't pull in `requests` for one POST."""
    boundary = f"----Auritus-{uuid.uuid4().hex}"
    crlf = b"\r\n"

    def part_header(disposition: str) -> bytes:
        return f"--{boundary}\r\n{disposition}\r\n\r\n".encode("utf-8")

    chunks: list[bytes] = []
    chunks.append(part_header(
        'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        'Content-Type: audio/wav'
    ))
    chunks.append(wav_bytes)
    chunks.append(crlf)

    fields = {
        "temperature":     "0.0",
        "response_format": "json",
        "language":        language,
    }
    for k, v in fields.items():
        chunks.append(part_header(f'Content-Disposition: form-data; name="{k}"'))
        chunks.append(v.encode("utf-8"))
        chunks.append(crlf)

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))

    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
