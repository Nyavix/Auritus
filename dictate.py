"""
Auritus - push-to-talk Whisper dictation tray app for Windows.

Toggle hotkey starts/stops a recording. On stop, audio is transcribed locally
with faster-whisper (CPU), copied to the clipboard, and pasted into the
focused window via Ctrl+V.

Run with `pythonw dictate.py` to suppress the console window.
"""

import sys
IS_WINDOWS = sys.platform.startswith("win")

# =====================================================================
# CONFIG -- edit these to taste
# =====================================================================

# Initial toggle hotkey, pynput GlobalHotKeys syntax. Examples:
#   "<ctrl>+<alt>+<space>"      (default)
#   "<ctrl>+<shift>+d"
#   "<f9>"
# After first run, the hotkey is editable from the tray menu and persisted
# in config.json. This constant is only the initial value used the very first
# launch (before config.json exists).
HOTKEY = "<ctrl>+<alt>+<space>"

# Cancel hotkey. Aborts the current recording (audio discarded) or, if pressed
# while a transcription is already in flight, drops the result before it
# reaches the clipboard. Independent of the main toggle/hold listener so it
# fires in every mode. Persisted to config.json after first launch.
CANCEL_HOTKEY = "<ctrl>+<f9>"

# Hotkey presets shown in the tray "Hotkey" submenu. Each entry is
# (pynput_spec, warning) -- warning is None for combos with no known conflict,
# or a short string shown next to the menu label.
HOTKEY_PRESETS = [
    ("<ctrl>+<alt>+<space>",      None),
    ("<f9>",                      None),
    ("<f12>",                     "browser DevTools"),
    ("<ctrl>+<alt>+<shift>+d",    None),
    ("<pause>",                   None),
    ("<scroll_lock>",             None),
    ("<ctrl>+<shift>+m",          "Teams/Outlook mute"),
    ("<ctrl>+<shift>+d",          None),
]

# faster-whisper model size. Options: tiny.en, base.en, small.en, medium.en,
# large-v3 (no .en variant). medium.en is a good CPU/quality tradeoff.
MODEL_SIZE = "medium.en"

# Quantization. int8 is fastest on CPU with minimal quality loss.
COMPUTE_TYPE = "int8"

# Mic device: None = system default. Otherwise an int index or substring of
# the device name (e.g. "Microphone (Realtek").  Run `python -m sounddevice`
# to list devices.
MIC_DEVICE = None

# Sample rate for capture. Whisper expects 16 kHz mono.
SAMPLE_RATE = 16000

# Max recording length in seconds. Hard cap to avoid runaway recordings.
MAX_RECORD_SECONDS = 300

# Auto-paste after transcription. If False, text is only put on the clipboard.
AUTO_PASTE = True

# Show toast notifications for routine events. Off by default on Windows
# (sounds + overlay are sufficient). On Linux the tkinter overlay is replaced
# by the GTK layer-shell pill, so toasts are the backup status channel.
SHOW_NOTIFICATIONS = not IS_WINDOWS

# Play a short sound when recording starts and stops.
PLAY_SOUNDS = True

# Write the full transcribed text into auritus.log. OFF by default: dictation
# can contain passwords, 2FA codes, and other secrets, and the log is a
# long-lived plaintext file. Turn on only for local debugging of bad output.
DEBUG_LOG_TEXT = False

# Optional custom .wav file paths. Leave None to use built-in synthesized tones.
SOUND_START = None  # e.g. r"C:\path\to\start.wav"
SOUND_STOP = None   # e.g. r"C:\path\to\stop.wav"

# Master volume for the built-in synthesized tones (0.0 - 1.0).
SOUND_VOLUME = 0.35

# Sound preset for the built-in tones. Options: "default", "subtle", "click".
# Overridable at runtime via the tray Sound submenu (persisted in config.json).
SOUND_PRESET = "default"

# Show the tkinter mic overlay while recording / transcribing.
# Windows only: on Linux the Wayland compositor owns the screen (tkinter
# would steal focus), so the GTK layer-shell pill is used instead.
SHOW_OVERLAY = IS_WINDOWS

# Overlay position on the primary screen: "top", "bottom", or "top-right".
OVERLAY_POSITION = "top"

# Distance in pixels from the screen edge.
OVERLAY_MARGIN = 40

# --- Overlay visual customization (P6) ---------------------------------
# Pixel size of the floating overlay. Width drives waveform resolution.
OVERLAY_WIDTH = 220
OVERLAY_HEIGHT = 48

# Panel fill (the "almost black" color behind the waveform).
OVERLAY_FILL_COLOR = "#0a0a0a"

# Window-wide opacity, 0.0 (invisible) to 1.0 (fully opaque). The whole panel
# fades together (border, waveform, text) -- this is what gives the
# see-through look. Recommended range: 0.55 - 0.85.
OVERLAY_OPACITY = 0.7

# Border color + thickness. White 3px is the default.
OVERLAY_ACCENT = "#ffffff"
OVERLAY_BORDER_WIDTH = 3

# Corner radius (px) for the rounded panel + border. Drawn on canvas so it
# works on every Windows version.
OVERLAY_CORNER_RADIUS = 14

# Waveform polyline color while recording.
OVERLAY_WAVE_COLOR = "#ff6868"

# Status text shown in the transcribing state. Recording state intentionally
# shows no label -- the waveform is the indicator.
OVERLAY_TRANSCRIBING_TEXT = "Transcribing"

# Models selectable from the tray menu. Smaller = faster, less accurate.
# Order matters: this is how they appear in the menu.
MODEL_OPTIONS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]

# Number of CPU threads for inference. 0 = let faster-whisper decide.
CPU_THREADS = 0

# Inference backend. Options:
#   "auto" -- use GPU (whisper.cpp Vulkan) when available, else CPU.
#   "gpu"  -- force whisper.cpp Vulkan. Errors loudly if no Vulkan device
#             is found or the binary isn't bundled.
#   "cpu"  -- force faster-whisper CPU (the original Auritus path).
# After first run, the choice is editable from the tray "Backend" submenu
# and persisted in config.json. This constant is only the initial value.
BACKEND = "auto"

# Valid BACKEND values, kept centralised for validation + the tray menu.
BACKEND_OPTIONS = ["auto", "gpu", "cpu"]

# =====================================================================

import os
import re
import io
import json
import math
import time
import queue
import socket
import hashlib
import struct
import ctypes
import tempfile
import threading
import traceback
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

if IS_WINDOWS:
    import winsound
else:
    winsound = None  # type: ignore[assignment]
    # AppIndicator (StatusNotifierItem) backend is required on modern Wayland
    # shells (niri, sway, KDE-on-Wayland).  The default auto-selection falls
    # back to legacy XEmbed which doesn't dock there.
    os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gtk, GtkLayerShell, GLib  # type: ignore[import]
    _HAVE_LAYER_SHELL = True
except Exception:
    Gtk = GtkLayerShell = GLib = None
    _HAVE_LAYER_SHELL = False

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

import pyperclip
from pynput import keyboard
from pynput.keyboard import Controller as KeyController, Key

from PIL import Image, ImageDraw
import pystray
import tkinter as tk

try:
    from plyer import notification as plyer_notification
except Exception:
    plyer_notification = None

from backends import Backend, FasterWhisperBackend, WhisperCppBackend


APP_NAME = "Auritus"
__version__ = "0.3.3"  # bumped in CI on tag push; user visible via update flow
if IS_WINDOWS:
    _DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
else:
    _xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    _DATA_DIR = Path(_xdg) / APP_NAME
LOG_PATH = _DATA_DIR / "auritus.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Best-effort: keep the log user-readable only (it may contain diagnostic text).
if not IS_WINDOWS:
    try:
        LOG_PATH.touch(exist_ok=True)
        os.chmod(LOG_PATH, 0o600)
    except Exception:
        pass


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def notify(title: str, message: str) -> None:
    if not SHOW_NOTIFICATIONS or plyer_notification is None:
        return
    try:
        plyer_notification.notify(title=title, message=message, app_name=APP_NAME, timeout=3)
    except Exception as e:
        log(f"notify failed: {e}")


def notify_error(title: str, message: str) -> None:
    """Errors always toast (regardless of SHOW_NOTIFICATIONS) and log."""
    log(f"ERROR {title}: {message}")
    if plyer_notification is None:
        return
    try:
        plyer_notification.notify(title=title, message=message, app_name=APP_NAME, timeout=4)
    except Exception as e:
        log(f"error-notify failed: {e}")


def notify_force(title: str, message: str, timeout: int = 4) -> None:
    """Always-on toast for diagnostics that should bypass SHOW_NOTIFICATIONS."""
    log(f"{title}: {message}")
    if plyer_notification is None:
        return
    try:
        plyer_notification.notify(title=title, message=message, app_name=APP_NAME, timeout=timeout)
    except Exception as e:
        log(f"force-notify failed: {e}")


# ---------------------------------------------------------------------
# Auto-update via GitHub Releases (P9)
# ---------------------------------------------------------------------
# On launch, a background thread polls the GitHub Releases API for the latest
# tag. If the tag is newer than __version__ and the release has an installer
# asset, the tray menu surfaces an "Install update" item. Clicking it
# downloads the installer and runs it silently; the installer's
# CloseApplications=force replaces the running app and relaunches.

UPDATE_REPO = "Nyavix/Auritus"
UPDATE_CHECK_DELAY_S = 30        # let the app fully start before hitting the network
UPDATE_API_TIMEOUT_S = 10
UPDATE_DOWNLOAD_TIMEOUT_S = 600  # installer can be ~100 MB on slow connections
_UPDATE_USER_AGENT = f"Auritus/{__version__} (+https://github.com/{UPDATE_REPO})"


def _parse_version(s: str) -> tuple[int, ...]:
    """'v0.2.1' or '0.2.1' -> (0, 2, 1). Stops at the first non-numeric piece
    so '1.0.0-rc1' parses as (1, 0) -- pre-release tags compare as older
    than a numeric-only release of the same prefix."""
    s = (s or "").strip().lstrip("vV")
    out: list[int] = []
    for piece in s.split("."):
        if not piece.isdigit():
            break
        out.append(int(piece))
    return tuple(out) if out else (0,)


def check_for_update() -> "tuple[str, str, str | None] | None":
    """Hit GitHub Releases /latest and return (tag, installer_url,
    expected_sha256_or_None) if a newer version is available. Returns None on
    any failure (offline, 404, no matching asset, already up to date)."""
    url = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UPDATE_USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=UPDATE_API_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    if _parse_version(tag) <= _parse_version(__version__):
        return None

    assets = data.get("assets", []) or []
    installer_url = None
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("Auritus-Setup") and name.endswith(".exe"):
            installer_url = asset.get("browser_download_url")
            break
    if not installer_url:
        return None

    # Optional integrity sidecar published by CI (Auritus-Setup-*.exe.sha256).
    expected_sha = None
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("Auritus-Setup") and name.endswith(".exe.sha256"):
            sha_url = asset.get("browser_download_url")
            if sha_url:
                try:
                    sreq = urllib.request.Request(sha_url, headers={"User-Agent": _UPDATE_USER_AGENT})
                    with urllib.request.urlopen(sreq, timeout=UPDATE_API_TIMEOUT_S) as r:
                        # sha256sum format is "<hex>  <filename>"; take the hex.
                        expected_sha = r.read().decode("utf-8", "replace").split()[0].strip() or None
                except Exception as e:
                    log(f"Update: could not fetch installer sha256 sidecar: {e}")
            break

    return tag.lstrip("vV"), installer_url, expected_sha


def download_installer(url: str, dest_path: str) -> str:
    """Stream an installer from `url` to `dest_path`; return its SHA256 hex digest.

    Raises OSError if the download is truncated (bytes written != Content-Length).
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UPDATE_USER_AGENT})
    h = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(req, timeout=UPDATE_DOWNLOAD_TIMEOUT_S) as resp, \
         open(dest_path, "wb") as f:
        clen = resp.headers.get("Content-Length")
        expected_len = int(clen) if clen and clen.isdigit() else None
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            written += len(chunk)
    if expected_len is not None and written != expected_len:
        raise OSError(f"installer download truncated: {written} of {expected_len} bytes")
    return h.hexdigest()


# ---------------------------------------------------------------------
# Persisted user config (model selection)
# ---------------------------------------------------------------------

CONFIG_PATH = _DATA_DIR / "config.json"


def load_user_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"config load failed: {e}")
    return {}


def save_user_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"config save failed: {e}")


def is_valid_hotkey(spec: str) -> bool:
    try:
        keyboard.HotKey.parse(spec)
        return True
    except Exception:
        return False


# --- Win32 RegisterHotKey conflict probe (P3) ---------------------------
# Detects the OS-level class of conflict (another app already registered the
# combo via RegisterHotKey). Does NOT detect WH_KEYBOARD_LL hook-swallow
# conflicts -- Teams / Discord / Outlook fall in the latter category and
# only the empirical "Test hotkey" diagnostic catches those.

_VK_SPECIAL = {
    "<space>": 0x20, "<tab>": 0x09, "<enter>": 0x0D,
    "<backspace>": 0x08, "<delete>": 0x2E, "<insert>": 0x2D,
    "<home>": 0x24, "<end>": 0x23,
    "<page_up>": 0x21, "<page_down>": 0x22,
    "<up>": 0x26, "<down>": 0x28, "<left>": 0x25, "<right>": 0x27,
    "<pause>": 0x13, "<scroll_lock>": 0x91, "<num_lock>": 0x90,
    "<caps_lock>": 0x14, "<print_screen>": 0x2C, "<esc>": 0x1B,
}

# US-layout OEM virtual-key codes for the punctuation keys we accept.
_VK_PUNCT = {
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE,
    "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}


def _key_to_vk(token: str) -> int | None:
    if token in _VK_SPECIAL:
        return _VK_SPECIAL[token]
    if token.startswith("<f") and token.endswith(">"):
        try:
            n = int(token[2:-1])
        except ValueError:
            return None
        if 1 <= n <= 24:
            return 0x6F + n  # VK_F1 = 0x70
        return None
    if len(token) == 1:
        if token.isalpha():
            return ord(token.upper())
        if token.isdigit():
            return ord(token)
        if token in _VK_PUNCT:
            return _VK_PUNCT[token]
    return None


def _spec_to_winhotkey(spec: str) -> tuple[int, int] | None:
    """Translate a pynput hotkey spec to (modifiers_mask, vk_code)."""
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
    mods = 0
    vk: int | None = None
    for raw in spec.split("+"):
        token = raw.strip().lower()
        if token == "<ctrl>":
            mods |= MOD_CONTROL
        elif token == "<shift>":
            mods |= MOD_SHIFT
        elif token == "<alt>":
            mods |= MOD_ALT
        elif token == "<cmd>":
            mods |= MOD_WIN
        else:
            v = _key_to_vk(token)
            if v is None:
                return None
            vk = v
    if vk is None:
        return None
    return mods, vk


_PROBE_ID_LOCK = threading.Lock()
_PROBE_ID_NEXT = 0xA51A


def _next_probe_id() -> int:
    """Rotate the RegisterHotKey ID per probe so a leaked registration
    (e.g. an UnregisterHotKey failure) doesn't spuriously flag every
    subsequent probe as conflict."""
    global _PROBE_ID_NEXT
    with _PROBE_ID_LOCK:
        v = _PROBE_ID_NEXT
        _PROBE_ID_NEXT += 1
        if _PROBE_ID_NEXT > 0xBFFF:  # app-defined IDs cap
            _PROBE_ID_NEXT = 0xA51A
        return v


def probe_hotkey_conflict(spec: str) -> tuple[bool, str]:
    """Try to claim `spec` via Win32 RegisterHotKey, then release it.

    Returns (available, message). `available=False` means another app has
    already registered the same combo. `available=True` with a non-empty
    message means we couldn't probe (unknown chord, non-Windows, etc.) and
    the caller should treat it as inconclusive rather than blocking.
    """
    if not sys.platform.startswith("win"):
        return True, "non-Windows: probe skipped"
    parsed = _spec_to_winhotkey(spec)
    if parsed is None:
        return True, "unmappable chord: probe skipped"
    mods, vk = parsed
    hotkey_id = _next_probe_id()
    user32 = ctypes.windll.user32
    user32.RegisterHotKey.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
    ]
    user32.RegisterHotKey.restype = ctypes.c_int
    user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.UnregisterHotKey.restype = ctypes.c_int
    ctypes.set_last_error(0)
    ok = user32.RegisterHotKey(None, hotkey_id, mods, vk)
    if not ok:
        err = ctypes.get_last_error()
        ERROR_HOTKEY_ALREADY_REGISTERED = 1409
        if err == ERROR_HOTKEY_ALREADY_REGISTERED:
            return False, "already registered by another app"
        return False, f"RegisterHotKey failed (err={err})"
    if not user32.UnregisterHotKey(None, hotkey_id):
        # Best effort -- next probe rotates the ID anyway.
        log(f"UnregisterHotKey({hex(hotkey_id)}) returned 0 after successful register")
    return True, ""


# --- Click-through helper for the overlay (P8) ------------------------
# Add WS_EX_TRANSPARENT so mouse clicks pass through the overlay window to
# whatever is underneath. Without this, clicking the panel can steal focus
# from the user's text field, killing the auto-paste flow. Also OR in
# WS_EX_LAYERED defensively (tk usually sets it via -alpha, but be explicit).

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000


def _make_window_clickthrough(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        cur = user32.GetWindowLongW(ctypes.c_void_p(hwnd), _GWL_EXSTYLE)
        new = cur | _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
        user32.SetWindowLongW(ctypes.c_void_p(hwnd), _GWL_EXSTYLE, new)
        return True
    except Exception as e:
        log(f"clickthrough apply failed: {e}")
        return False


# --- Rounded-rectangle helper for the overlay (P6) --------------------
# Tk's Canvas has no native rounded rectangle. The standard recipe is a
# 20-point polygon with `smooth=True` -- duplicate points produce straight
# segments, single corner points get bezier-smoothed. Both fill and stroke
# follow the rounded path, so a single create_polygon call gives us a clean
# rounded-rect with optional border.

def _round_rect_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    return [
        x1 + r, y1,    x1 + r, y1,
        x2 - r, y1,    x2 - r, y1,
        x2,     y1,
        x2,     y1 + r,    x2, y1 + r,
        x2,     y2 - r,    x2, y2 - r,
        x2,     y2,
        x2 - r, y2,    x2 - r, y2,
        x1 + r, y2,    x1 + r, y2,
        x1,     y2,
        x1,     y2 - r,    x1, y2 - r,
        x1,     y1 + r,    x1, y1 + r,
        x1,     y1,
    ]


# --- Hold-mode chord tracker (P2) --------------------------------------
# pynput's built-in HotKey class only fires on chord activation (all keys
# down). Hold-to-talk needs the deactivation edge too. _HoldChord is fed
# canonical key events from a `keyboard.Listener` and emits engage/release
# transitions exactly once per chord cycle.

class _HoldChord:
    """Tracks press/release transitions for a parsed pynput chord.

    Edge-triggered: `on_engage` fires on the rising edge (full chord first
    held), `on_release` fires on the falling edge (any target key released
    while engaged). Auto-repeat key-presses do not retrigger engage.

    Internal state is guarded by a lock; callbacks are invoked OUTSIDE the
    lock so a callback that re-enters press/release can't deadlock.
    """

    def __init__(self, keys, on_engage, on_release):
        self._target = set(keys)
        self._held: set = set()
        self._engaged: bool = False
        self._on_engage = on_engage
        self._on_release = on_release
        self._lock = threading.Lock()

    def press(self, key) -> None:
        if key not in self._target:
            return
        fire = False
        with self._lock:
            self._held.add(key)
            if not self._engaged and self._held == self._target:
                self._engaged = True
                fire = True
        if fire:
            try:
                self._on_engage()
            except Exception as e:
                log(f"hold on_engage error: {e}\n{traceback.format_exc()}")

    def release(self, key) -> None:
        if key not in self._target:
            return
        fire = False
        with self._lock:
            self._held.discard(key)
            if self._engaged and self._held != self._target:
                self._engaged = False
                fire = True
        if fire:
            try:
                self._on_release()
            except Exception as e:
                log(f"hold on_release error: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------
# Sound effects (synthesized in-memory WAV played via winsound)
# ---------------------------------------------------------------------

def _make_wav_tone(segments: list, sample_rate: int = 44100, volume: float = 0.35) -> bytes:
    """segments: list of (frequency_hz, duration_seconds). Returns WAV bytes."""
    pieces = []
    for freq, dur in segments:
        n = max(1, int(sample_rate * dur))
        t = np.arange(n) / sample_rate
        wave = np.sin(2 * np.pi * float(freq) * t)
        # Short fade in/out to avoid clicks.
        fade = max(1, int(0.005 * sample_rate))
        env = np.ones(n, dtype=np.float64)
        env[:fade] = np.linspace(0, 1, fade)
        env[-fade:] = np.linspace(1, 0, fade)
        pieces.append(wave * env * volume)
    full = np.concatenate(pieces) if pieces else np.zeros(0)
    pcm = (np.clip(full, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    n_channels = 1
    bits = 16
    byte_rate = sample_rate * n_channels * bits // 8
    block_align = n_channels * bits // 8
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, n_channels, sample_rate, byte_rate, block_align, bits)
        + b"data" + struct.pack("<I", len(pcm))
    )
    return header + pcm


# Preset tone definitions. Each entry: start/stop note sequences + volume.
SOUND_PRESETS = {
    "default": {"start": [(660, 0.06), (990, 0.09)], "stop": [(880, 0.06), (587, 0.10)], "volume": 0.35},
    "subtle":  {"start": [(880, 0.05)],               "stop": [(660, 0.05)],              "volume": 0.18},
    "click":   {"start": [(1200, 0.03)],              "stop": [(900, 0.03)],              "volume": 0.22},
}


def _write_temp_wav(data: bytes, name: str) -> str | None:
    try:
        path = os.path.join(tempfile.gettempdir(), f"auritus_{name}.wav")
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception as e:
        log(f"failed to write temp wav {name}: {e}")
        return None


# Pre-generate a temp WAV file for every preset so switching is instant.
_PRESET_WAV_PATHS: dict[str, dict[str, str | None]] = {}
for _pname, _pdef in SOUND_PRESETS.items():
    _PRESET_WAV_PATHS[_pname] = {
        "start": _write_temp_wav(
            _make_wav_tone(_pdef["start"], volume=_pdef["volume"]), f"preset_{_pname}_start"
        ),
        "stop": _write_temp_wav(
            _make_wav_tone(_pdef["stop"], volume=_pdef["volume"]), f"preset_{_pname}_stop"
        ),
    }

# Runtime-mutable sound state; updated by DictateApp, read by play_sound.
_sounds_muted: bool = False
_current_preset: str = "default"


def _play_wav_async(path: str) -> None:
    """Play a WAV file without blocking. Per-platform backend."""
    if IS_WINDOWS:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)  # type: ignore[union-attr]
    else:
        rate, data = wavfile.read(path)
        sd.play(data, rate)


def _beep_fallback(kind: str) -> None:
    """Last-resort tone. Synchronous, run on a worker thread.
    Linux: silent (synthesized WAV is the practical fallback; no further path)."""
    if not IS_WINDOWS:
        log(f"beep fallback unavailable on non-Windows ({kind})")
        return
    try:
        if kind == "start":
            winsound.Beep(660, 60); winsound.Beep(990, 90)  # type: ignore[union-attr]
        else:
            winsound.Beep(880, 60); winsound.Beep(587, 100)  # type: ignore[union-attr]
    except Exception as e:
        log(f"Beep fallback failed: {e}")


def play_sound(kind: str) -> None:
    """kind = 'start' or 'stop'. Always returns immediately."""
    if not PLAY_SOUNDS or _sounds_muted:
        return

    def _play():
        log(f"play_sound({kind})")
        # 1. Custom user-supplied WAV
        custom = SOUND_START if kind == "start" else SOUND_STOP
        if custom and os.path.isfile(custom):
            try:
                _play_wav_async(custom)
                return
            except Exception as e:
                log(f"play_wav({custom}) failed: {e}")

        # 2. Preset synthesized WAV
        preset_paths = _PRESET_WAV_PATHS.get(_current_preset) or _PRESET_WAV_PATHS.get("default", {})
        path = preset_paths.get(kind)
        if path and os.path.isfile(path):
            try:
                _play_wav_async(path)
                return
            except Exception as e:
                log(f"play_wav({path}) failed: {e}")

        # 3. Guaranteed fallback
        _beep_fallback(kind)

    threading.Thread(target=_play, daemon=True).start()


# ---------------------------------------------------------------------
# Tray icons
# ---------------------------------------------------------------------

def _make_icon(color: tuple) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=color, outline=(30, 30, 30, 255), width=2)
    return img

ICON_IDLE = _make_icon((80, 140, 220, 255))      # blue
ICON_RECORDING = _make_icon((220, 60, 60, 255))  # red
ICON_BUSY = _make_icon((220, 180, 60, 255))      # amber


# ---------------------------------------------------------------------
# Recording overlay -- glass panel with live waveform (P6)
# ---------------------------------------------------------------------

class RecordingOverlay:
    """Two-window floating overlay.

    Layered design so the user can have a translucent panel with crisp,
    fully-opaque content on top:

      * `_bg_root`  — translucent dark rounded panel (alpha = OVERLAY_OPACITY)
      * `_fg_root`  — opaque rounded border + status dot + waveform + label
                       (alpha = 1.0, transparent everywhere else)

    Both windows are frameless, topmost, and move/show/hide together. The
    rounded shape is drawn on canvas so it works on every Windows version
    (no DWM dependency). A magic transparent-color key cuts the rectangular
    window down to the rounded outline.
    """

    TRANSPARENT_KEY = "#010203"   # near-black sentinel used as alpha mask
    TEXT_COLOR = "#e8eef5"
    DOT_RECORDING = "#ff6868"
    DOT_TRANSCRIBING = "#f0c85a"
    POLL_MS = 33                  # ~30 fps refresh
    WAVE_DURATION_S = 0.15        # window of audio shown in the waveform

    def __init__(self, recorder: "Recorder"):
        self._recorder = recorder
        self._thread: threading.Thread | None = None
        self._bg_root: tk.Tk | None = None
        self._fg_root: tk.Toplevel | None = None
        self._bg_canvas: tk.Canvas | None = None
        self._fg_canvas: tk.Canvas | None = None
        self._bg_panel_id: int = 0
        self._border_id: int = 0
        self._wave_id: int = 0
        self._dot_id: int = 0
        self._text_id: int = 0
        self._state: str = "recording"
        self._visible: bool = False
        self._poll_handle = None
        self._pulse_phase: float = 0.0
        self._wave_points: int = 0
        self._wave_x0: int = 0
        self._wave_x1: int = 0
        self._clickthrough_applied: bool = False
        self._ready = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="overlay")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run(self) -> None:
        try:
            W, H = OVERLAY_WIDTH, OVERLAY_HEIGHT
            BW = OVERLAY_BORDER_WIDTH
            R = OVERLAY_CORNER_RADIUS
            inset = BW / 2.0
            panel_pts = _round_rect_points(inset, inset, W - inset, H - inset, R)

            # --- BG window: translucent rounded fill ---------------------
            # className sets WM_CLASS so Wayland compositors (niri) can match
            # window-rules against app-id="AriasSTTOverlay".
            bg = tk.Tk(className="AuritusOverlay")
            bg.withdraw()
            bg.overrideredirect(True)
            bg.attributes("-topmost", True)
            bg.geometry(f"{W}x{H}")
            bg.resizable(False, False)
            bg.configure(bg=self.TRANSPARENT_KEY)
            if IS_WINDOWS:
                try:
                    bg.attributes("-transparentcolor", self.TRANSPARENT_KEY)
                except Exception as e:
                    log(f"overlay bg transparentcolor failed: {e}")
            try:
                bg.attributes("-alpha", float(OVERLAY_OPACITY))
            except Exception as e:
                log(f"overlay bg alpha failed: {e}")

            bg_canvas = tk.Canvas(
                bg, width=W, height=H,
                bg=self.TRANSPARENT_KEY,
                highlightthickness=0, borderwidth=0,
            )
            bg_canvas.pack(fill="both", expand=True)
            self._bg_panel_id = bg_canvas.create_polygon(
                *panel_pts, smooth=True,
                fill=OVERLAY_FILL_COLOR, outline="", width=0,
            )

            # --- FG window: opaque border + content ---------------------
            fg = tk.Toplevel(bg)
            fg.withdraw()
            fg.overrideredirect(True)
            fg.attributes("-topmost", True)
            fg.geometry(f"{W}x{H}")
            fg.resizable(False, False)
            fg.configure(bg=self.TRANSPARENT_KEY)
            if IS_WINDOWS:
                try:
                    fg.attributes("-transparentcolor", self.TRANSPARENT_KEY)
                except Exception as e:
                    log(f"overlay fg transparentcolor failed: {e}")
            try:
                fg.attributes("-alpha", 1.0)
            except Exception:
                pass

            fg_canvas = tk.Canvas(
                fg, width=W, height=H,
                bg=self.TRANSPARENT_KEY,
                highlightthickness=0, borderwidth=0,
            )
            fg_canvas.pack(fill="both", expand=True)

            # White rounded border, no fill (lets the bg panel show through).
            self._border_id = fg_canvas.create_polygon(
                *panel_pts, smooth=True,
                fill="", outline=OVERLAY_ACCENT, width=BW,
            )

            # Status dot tucked away from the rounded corner.
            dot_r = max(3, H // 10)
            dot_cx = BW + R // 2 + dot_r
            dot_cy = H // 2
            self._dot_id = fg_canvas.create_oval(
                dot_cx - dot_r, dot_cy - dot_r,
                dot_cx + dot_r, dot_cy + dot_r,
                fill=self.DOT_RECORDING, outline="",
            )

            # Waveform spans from just right of the dot to just before the right border arc.
            self._wave_x0 = dot_cx + dot_r + 6
            self._wave_x1 = W - BW - R // 2 - 4
            self._wave_points = max(20, (self._wave_x1 - self._wave_x0) // 3)
            cy = H // 2
            flat = []
            for i in range(self._wave_points):
                x = self._wave_x0 + (self._wave_x1 - self._wave_x0) * i / max(1, self._wave_points - 1)
                flat.extend([x, cy])
            self._wave_id = fg_canvas.create_line(
                *flat,
                fill=OVERLAY_WAVE_COLOR, width=2, smooth=True, capstyle="round",
            )

            # Centered status text (used in the transcribing state).
            self._text_id = fg_canvas.create_text(
                W // 2, H // 2,
                text="", fill=self.TEXT_COLOR,
                font=("Segoe UI", 11, "bold"),
            )

            self._bg_root = bg
            self._fg_root = fg
            self._bg_canvas = bg_canvas
            self._fg_canvas = fg_canvas
            self._ready.set()
            bg.mainloop()
        except Exception as e:
            log(f"overlay thread error: {e}\n{traceback.format_exc()}")
            self._ready.set()

    # -- thread-safe public API -------------------------------------------

    def show(self, state: str = "recording") -> None:
        if self._bg_root is None:
            return
        try:
            self._bg_root.after(0, lambda: self._do_show(state))
        except Exception as e:
            log(f"overlay show error: {e}")

    def set_state(self, state: str) -> None:
        if self._bg_root is None:
            return
        try:
            self._bg_root.after(0, lambda: self._do_set_state(state))
        except Exception as e:
            log(f"overlay set_state error: {e}")

    def hide(self) -> None:
        if self._bg_root is None:
            return
        try:
            self._bg_root.after(0, self._do_hide)
        except Exception as e:
            log(f"overlay hide error: {e}")

    def stop(self) -> None:
        if self._bg_root is None:
            return
        try:
            self._bg_root.after(0, self._destroy)
        except Exception:
            pass

    # -- overlay-thread handlers ------------------------------------------

    def _destroy(self) -> None:
        # Stop the per-frame redraw before destroying the canvases so an
        # in-flight after() callback doesn't fire on a destroyed widget.
        self._visible = False
        if self._poll_handle is not None and self._bg_root is not None:
            try:
                self._bg_root.after_cancel(self._poll_handle)
            except Exception:
                pass
            self._poll_handle = None
        try:
            if self._fg_root is not None:
                self._fg_root.destroy()
        except Exception:
            pass
        try:
            if self._bg_root is not None:
                self._bg_root.destroy()
        except Exception:
            pass

    def _do_show(self, state: str) -> None:
        self._reposition()
        self._do_set_state(state)
        if self._bg_root is not None:
            self._bg_root.deiconify()
            self._bg_root.attributes("-topmost", True)
        if self._fg_root is not None:
            self._fg_root.deiconify()
            self._fg_root.attributes("-topmost", True)
            try:
                self._fg_root.lift(self._bg_root)
            except Exception:
                pass
        # Apply click-through once both windows have real HWNDs (post-deiconify).
        if not self._clickthrough_applied:
            self._apply_clickthrough()
            self._clickthrough_applied = True
        self._visible = True
        self._tick()

    def _apply_clickthrough(self) -> None:
        """Mark both overlay HWNDs as transparent to mouse input so clicks
        pass through to whatever's underneath (typically the user's text
        field). Without this, an accidental click on the overlay would steal
        focus and break the auto-paste flow."""
        for root in (self._bg_root, self._fg_root):
            if root is None:
                continue
            try:
                inner = root.winfo_id()
                top = ctypes.windll.user32.GetParent(inner)
                hwnd = top if top else inner
            except Exception as e:
                log(f"clickthrough HWND lookup failed: {e}")
                continue
            _make_window_clickthrough(hwnd)

    def _do_set_state(self, state: str) -> None:
        if self._fg_canvas is None:
            return
        self._state = state
        if state == "recording":
            self._fg_canvas.itemconfigure(self._dot_id, fill=self.DOT_RECORDING)
            self._fg_canvas.itemconfigure(self._text_id, text="")
            self._fg_canvas.itemconfigure(self._wave_id, state="normal", fill=OVERLAY_WAVE_COLOR)
        elif state == "transcribing":
            self._fg_canvas.itemconfigure(self._dot_id, fill=self.DOT_TRANSCRIBING)
            self._fg_canvas.itemconfigure(
                self._text_id, text=OVERLAY_TRANSCRIBING_TEXT, fill=self.DOT_TRANSCRIBING,
            )
            self._fg_canvas.itemconfigure(self._wave_id, state="hidden")

    def _do_hide(self) -> None:
        self._visible = False
        if self._poll_handle is not None and self._bg_root is not None:
            try:
                self._bg_root.after_cancel(self._poll_handle)
            except Exception:
                pass
            self._poll_handle = None
        if self._fg_root is not None:
            self._fg_root.withdraw()
        if self._bg_root is not None:
            self._bg_root.withdraw()

    def _reposition(self) -> None:
        if self._bg_root is None:
            return
        sw = self._bg_root.winfo_screenwidth()
        sh = self._bg_root.winfo_screenheight()
        ww = OVERLAY_WIDTH
        wh = OVERLAY_HEIGHT
        pos = (OVERLAY_POSITION or "top").lower()
        if pos == "bottom":
            x = (sw - ww) // 2
            y = sh - wh - OVERLAY_MARGIN
        elif pos in ("top-right", "topright"):
            x = sw - ww - OVERLAY_MARGIN
            y = OVERLAY_MARGIN
        else:  # "top"
            x = (sw - ww) // 2
            y = OVERLAY_MARGIN
        geom = f"{ww}x{wh}+{x}+{y}"
        self._bg_root.geometry(geom)
        if self._fg_root is not None:
            self._fg_root.geometry(geom)

    # -- per-frame draw ---------------------------------------------------

    def _tick(self) -> None:
        if not self._visible or self._fg_canvas is None or self._bg_root is None:
            return
        if self._state == "recording":
            self._draw_wave()
        elif self._state == "transcribing":
            self._draw_pulse()
        try:
            self._poll_handle = self._bg_root.after(self.POLL_MS, self._tick)
        except Exception:
            self._poll_handle = None

    def _draw_wave(self) -> None:
        try:
            samples = self._recorder.peek_recent_samples(self.WAVE_DURATION_S)
        except Exception as e:
            log(f"overlay peek error: {e}")
            return
        N = self._wave_points
        if samples.size < 4:
            ds = np.zeros(N, dtype=np.float32)
        else:
            step = max(1, len(samples) // N)
            ds = samples[::step][:N]
            if len(ds) < N:
                ds = np.concatenate([np.zeros(N - len(ds), dtype=np.float32), ds])
        # Normalize so a normal speaking voice fills most of the panel without
        # clipping; very quiet input stays visibly small instead of jumping to
        # full amplitude.
        peak = float(np.max(np.abs(ds))) if ds.size else 0.0
        floor = 0.05
        if peak < 1e-4:
            norm = ds  # silence: flat line
        else:
            scale = 1.0 / max(peak, floor)
            norm = ds * scale
            if peak < floor:
                norm = norm * (peak / floor)
        cy = OVERLAY_HEIGHT // 2
        amp = (OVERLAY_HEIGHT // 2) - OVERLAY_BORDER_WIDTH - 4
        x0, x1 = self._wave_x0, self._wave_x1
        denom = max(1, N - 1)
        pts: list[float] = []
        for i in range(N):
            x = x0 + (x1 - x0) * i / denom
            y = cy - float(norm[i]) * amp
            pts.append(x)
            pts.append(y)
        try:
            self._fg_canvas.coords(self._wave_id, *pts)
        except Exception as e:
            log(f"overlay coords error: {e}")

    def _draw_pulse(self) -> None:
        self._pulse_phase += self.POLL_MS / 1000.0 * 4.0  # ~4 rad/s
        s = (math.sin(self._pulse_phase) + 1.0) / 2.0  # 0..1
        r = 4.0 + 3.0 * s
        BW = OVERLAY_BORDER_WIDTH
        R = OVERLAY_CORNER_RADIUS
        dot_r_static = max(3, OVERLAY_HEIGHT // 10)
        cx = float(BW + R // 2 + dot_r_static)
        cy = OVERLAY_HEIGHT / 2.0
        try:
            self._fg_canvas.coords(self._dot_id, cx - r, cy - r, cx + r, cy + r)
        except Exception:
            pass


# ---------------------------------------------------------------------
# Wayland layer-shell recording indicator (Linux only)
# ---------------------------------------------------------------------

class LayerShellIndicator:
    """Tiny GTK window pinned via wlr-layer-shell so niri (or any Wayland
    compositor with layer-shell support) can't tile or focus it. Replaces
    the tk overlay on Linux. State updates marshal to the GTK main thread
    via GLib.idle_add since they originate from the recorder/transcribe threads.
    Falls back gracefully when gtk-layer-shell is not installed.
    """

    _STATES = {
        "recording":    ("Recording",    "#e83c3c"),
        "transcribing": ("Transcribing", "#dcb43c"),
    }

    def __init__(self) -> None:
        self._win = None
        self._label = None
        self._built = False

    def _build(self) -> None:
        if self._built or not _HAVE_LAYER_SHELL:
            return
        # Mark attempted early so a failed build doesn't spam on every show().
        self._built = True
        try:
            win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            win.set_default_size(180, 40)
            win.set_app_paintable(True)
            screen = win.get_screen()
            visual = screen.get_rgba_visual()
            if visual is not None:
                win.set_visual(visual)
            GtkLayerShell.init_for_window(win)
            GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, 24)
            GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, 24)
            GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(win, 0)
            label = Gtk.Label()
            label.set_use_markup(True)
            label.set_padding(16, 8)
            win.add(label)
            css = b"window { background: rgba(20,20,24,0.92); border-radius: 10px; } label { color: #f0f0f0; font-family: sans-serif; font-size: 13px; }"
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self._win = win
            self._label = label
        except Exception as e:
            log(f"LayerShell build failed (indicator disabled): {e}")

    def show(self, state: str) -> None:
        if _HAVE_LAYER_SHELL:
            GLib.idle_add(self._show_impl, state)

    def hide(self) -> None:
        if _HAVE_LAYER_SHELL:
            GLib.idle_add(self._hide_impl)

    def stop(self) -> None:
        if _HAVE_LAYER_SHELL:
            GLib.idle_add(self._destroy_impl)

    def _show_impl(self, state: str) -> bool:
        try:
            self._build()
            if self._win is None:
                return False
            text, color = self._STATES.get(state, (state.title(), "#7888aa"))
            self._label.set_markup(f'<span foreground="{color}" size="larger">●</span>  <span foreground="#f0f0f0">{text}</span>')
            self._win.show_all()
        except Exception as e:
            log(f"indicator show failed: {e}")
        return False

    def _hide_impl(self) -> bool:
        try:
            if self._win is not None:
                self._win.hide()
        except Exception as e:
            log(f"indicator hide failed: {e}")
        return False

    def _destroy_impl(self) -> bool:
        try:
            if self._win is not None:
                self._win.destroy()
                self._win = None
                self._built = False
        except Exception as e:
            log(f"indicator destroy failed: {e}")
        return False


# ---------------------------------------------------------------------
# Hotkey capture dialog
# ---------------------------------------------------------------------

class HotkeyCaptureDialog:
    """Modal Toplevel that records a key chord and returns a pynput hotkey
    string. Runs on its own thread with its own tk.Tk root (multi-root
    pattern matches RecordingOverlay)."""

    MODIFIER_KEYSYMS = {
        "Control_L": "ctrl",  "Control_R": "ctrl",
        "Shift_L":   "shift", "Shift_R":   "shift",
        "Alt_L":     "alt",   "Alt_R":     "alt",
        "Meta_L":    "alt",   "Meta_R":    "alt",
        "Super_L":   "cmd",   "Super_R":   "cmd",
        "Win_L":     "cmd",   "Win_R":     "cmd",
    }

    SPECIAL_KEYS = {
        "space": "<space>", "Tab": "<tab>", "Return": "<enter>",
        "BackSpace": "<backspace>", "Delete": "<delete>", "Insert": "<insert>",
        "Home": "<home>", "End": "<end>",
        "Prior": "<page_up>", "Next": "<page_down>",
        "Up": "<up>", "Down": "<down>", "Left": "<left>", "Right": "<right>",
        "Pause": "<pause>", "Scroll_Lock": "<scroll_lock>",
        "Num_Lock": "<num_lock>", "Caps_Lock": "<caps_lock>",
        "Print": "<print_screen>",
    }

    PUNCTUATION = {
        "minus": "-", "plus": "+", "equal": "=",
        "comma": ",", "period": ".", "slash": "/", "backslash": "\\",
        "semicolon": ";", "apostrophe": "'", "grave": "`",
        "bracketleft": "[", "bracketright": "]",
    }

    BG = "#1a1a1a"
    PANEL = "#0f0f0f"
    FG = "#e0e0e0"
    DIM = "#888888"
    ACCENT = "#5cc8ff"
    OK = "#7be38a"
    ERR = "#ff6868"
    BTN_BG = "#2a2a2a"
    BTN_HOVER = "#3a3a3a"
    PRIMARY = "#2c5282"
    PRIMARY_HOVER = "#3b6ba5"

    def __init__(self, app: "DictateApp"):
        self.app = app
        self._held_mods: set[str] = set()
        self._held_main: str | None = None
        self._locked: tuple[frozenset, str] | None = None
        self._result: str | None = None
        self._root: tk.Tk | None = None
        self._preview: tk.Label | None = None
        self._status: tk.Label | None = None
        self._ok_btn: tk.Button | None = None

    def run(self) -> None:
        root = tk.Tk()
        root.withdraw()
        root.title(f"{APP_NAME} — Set hotkey")
        root.configure(bg=self.BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)
        self._root = root

        outer = tk.Frame(root, bg=self.BG, padx=26, pady=22)
        outer.pack()

        tk.Label(
            outer, text="Press the key combination",
            bg=self.BG, fg=self.FG, font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")

        tk.Label(
            outer,
            text="Hold modifiers (Ctrl, Shift, Alt, Win) and press a key.\n"
                 "Esc to cancel  ·  Clear to reset  ·  OK to save.",
            bg=self.BG, fg=self.DIM, font=("Segoe UI", 9), justify="left",
        ).pack(anchor="w", pady=(4, 14))

        self._preview = tk.Label(
            outer, text="(waiting for keys…)",
            bg=self.PANEL, fg=self.DIM, font=("Segoe UI", 14, "bold"),
            padx=16, pady=12, anchor="center", width=32,
        )
        self._preview.pack(fill="x")

        self._status = tk.Label(
            outer, text="Tip: triple-modifier chords (Ctrl+Alt+Shift+key) rarely conflict.",
            bg=self.BG, fg=self.DIM, font=("Segoe UI", 9), justify="left",
        )
        self._status.pack(anchor="w", pady=(10, 16))

        btns = tk.Frame(outer, bg=self.BG)
        btns.pack(fill="x")

        self._make_button(btns, "Clear", self._on_clear).pack(side="left")
        self._make_button(btns, "Cancel", self._on_cancel).pack(side="right")
        self._ok_btn = self._make_button(
            btns, "OK", self._on_ok, primary=True
        )
        self._ok_btn.pack(side="right", padx=(0, 8))
        self._ok_btn.configure(state="disabled")

        root.bind_all("<KeyPress>", self._on_key_press)
        root.bind_all("<KeyRelease>", self._on_key_release)
        root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        ww = root.winfo_reqwidth()
        wh = root.winfo_reqheight()
        x = (sw - ww) // 2
        y = (sh - wh) // 3
        root.geometry(f"+{x}+{y}")
        root.deiconify()
        root.focus_force()
        try:
            root.grab_set()
        except Exception:
            pass

        root.mainloop()

        if self._result:
            self.app.set_hotkey(self._result)

    def _make_button(self, parent: tk.Frame, text: str, command, primary: bool = False) -> tk.Button:
        bg = self.PRIMARY if primary else self.BTN_BG
        hover = self.PRIMARY_HOVER if primary else self.BTN_HOVER
        fg = "#ffffff" if primary else self.FG
        btn = tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
            relief="flat", borderwidth=0, padx=18, pady=7,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            cursor="hand2",
        )
        btn.bind("<Enter>", lambda _e, b=btn, c=hover: b.configure(bg=c))
        btn.bind("<Leave>", lambda _e, b=btn, c=bg: b.configure(bg=c))
        return btn

    # -- key handling -------------------------------------------------

    def _on_key_press(self, event):
        sym = event.keysym
        if sym == "Escape" and not self._held_mods and not self._held_main and self._locked is None:
            self._on_cancel()
            return "break"
        if sym in self.MODIFIER_KEYSYMS:
            self._held_mods.add(self.MODIFIER_KEYSYMS[sym])
            self._update_preview()
            return "break"
        main = self._keysym_to_pynput(sym)
        if main is None:
            self._set_status(f"Unsupported key: {sym}", error=True)
            return "break"
        self._held_main = main
        self._locked = (frozenset(self._held_mods), main)
        self._set_status("Press OK to save, Clear to retry.")
        self._update_preview()
        return "break"

    def _on_key_release(self, event):
        sym = event.keysym
        if sym in self.MODIFIER_KEYSYMS:
            self._held_mods.discard(self.MODIFIER_KEYSYMS[sym])
        else:
            main = self._keysym_to_pynput(sym)
            if main and self._held_main == main:
                self._held_main = None
        self._update_preview()
        return "break"

    # -- buttons ------------------------------------------------------

    def _on_clear(self):
        self._held_mods.clear()
        self._held_main = None
        self._locked = None
        self._set_status("")
        self._update_preview()

    def _on_cancel(self):
        self._result = None
        try:
            self._root.grab_release()
        except Exception:
            pass
        self._root.destroy()

    def _on_ok(self):
        spec = self._build_spec()
        if not spec:
            self._set_status("Need at least one non-modifier key.", error=True)
            return
        if not is_valid_hotkey(spec):
            self._set_status(f"Invalid hotkey: {spec}", error=True)
            return
        self._result = spec
        try:
            self._root.grab_release()
        except Exception:
            pass
        self._root.destroy()

    # -- preview ------------------------------------------------------

    def _build_spec(self) -> str | None:
        if not self._locked:
            return None
        mods, main = self._locked
        order = ["ctrl", "alt", "shift", "cmd"]
        parts = [f"<{m}>" for m in order if m in mods]
        parts.append(main)
        return "+".join(parts)

    def _update_preview(self):
        if self._preview is None or self._ok_btn is None:
            return
        if self._locked:
            spec = self._build_spec() or ""
            self._preview.configure(text=self._pretty(spec), fg=self.OK)
            self._ok_btn.configure(state="normal")
            return
        if self._held_mods or self._held_main:
            order = ["ctrl", "alt", "shift", "cmd"]
            parts = [f"<{m}>" for m in order if m in self._held_mods]
            if self._held_main:
                parts.append(self._held_main)
            preview = "+".join(parts) if parts else ""
            self._preview.configure(
                text=self._pretty(preview) if preview else "(waiting for keys…)",
                fg=self.ACCENT,
            )
        else:
            self._preview.configure(text="(waiting for keys…)", fg=self.DIM)
        self._ok_btn.configure(state="disabled")

    def _set_status(self, text: str, error: bool = False):
        if self._status is None:
            return
        self._status.configure(text=text, fg=self.ERR if error else self.DIM)

    @staticmethod
    def _pretty(spec: str) -> str:
        out = []
        for part in spec.split("+"):
            p = part.strip()
            if p.startswith("<") and p.endswith(">"):
                inner = p[1:-1]
                out.append(inner.replace("_", " ").title())
            else:
                out.append(p.upper() if len(p) == 1 else p)
        return "  +  ".join(out)

    @classmethod
    def _keysym_to_pynput(cls, sym: str) -> str | None:
        if sym in cls.SPECIAL_KEYS:
            return cls.SPECIAL_KEYS[sym]
        if len(sym) >= 2 and sym[0] in "Ff" and sym[1:].isdigit():
            n = int(sym[1:])
            if 1 <= n <= 20:
                return f"<f{n}>"
        if len(sym) == 1:
            if sym.isalpha():
                return sym.lower()
            if sym.isdigit():
                return sym
            if not sym.isspace():
                return sym
        if sym in cls.PUNCTUATION:
            return cls.PUNCTUATION[sym]
        return None


# ---------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------

class Recorder:
    """Captures mono float32 audio at SAMPLE_RATE into an in-memory buffer."""

    def __init__(self):
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._start_time = 0.0

    def start(self) -> None:
        self._chunks = []
        self._start_time = time.time()

        def callback(indata, frames, time_info, status):
            if status:
                log(f"sounddevice status: {status}")
            with self._lock:
                self._chunks.append(indata.copy())
            if time.time() - self._start_time > MAX_RECORD_SECONDS:
                # Stop will be triggered by the main toggle path; just drop further data.
                pass

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=MIC_DEVICE,
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log(f"stream close error: {e}")
            self._stream = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks, axis=0).flatten()
            self._chunks = []
        return audio

    def peek_recent_samples(self, seconds: float) -> np.ndarray:
        """Return up to `seconds` worth of the most recent audio without
        consuming it. Safe to call from another thread; cheap because we
        only walk the tail of the chunk list.
        """
        n_target = int(seconds * SAMPLE_RATE)
        if n_target <= 0:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            tail: list[np.ndarray] = []
            total = 0
            for chunk in reversed(self._chunks):
                tail.append(chunk)
                total += len(chunk)
                if total >= n_target:
                    break
            tail.reverse()
            audio = np.concatenate(tail, axis=0).flatten()
        if len(audio) > n_target:
            audio = audio[-n_target:]
        return audio


# ---------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------

# Strip leading/trailing whisper-style timestamps and bracketed segment markers
# that some pipelines leak into the text.
_TIMESTAMP_RE = re.compile(
    r"\s*\[?\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*-->\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*\]?\s*"
)
_BRACKET_TS_RE = re.compile(r"\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*\]")
_INLINE_TS_RE = re.compile(r"<\|\d+\.\d+\|>")


def clean_text(text: str) -> str:
    text = _TIMESTAMP_RE.sub(" ", text)
    text = _BRACKET_TS_RE.sub(" ", text)
    text = _INLINE_TS_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------
# Paste helper
# ---------------------------------------------------------------------

def paste_clipboard(text: str = "") -> bool:
    """Insert transcribed text into the focused window. Returns True on success.

    Windows: synthesizes Ctrl+V to paste from clipboard.
    Linux/Wayland: types ``text`` directly via wtype (skips clipboard race;
    text is also on the clipboard via pyperclip.copy as a manual-paste fallback).
    """
    if not IS_WINDOWS:
        if not text:
            log("paste skipped: no text passed (Linux path needs explicit text)")
            return False
        try:
            subprocess.run(["wtype", "--", text], check=True, timeout=10)
            return True
        except FileNotFoundError:
            log("paste failed: wtype not installed (pacman -S wtype)")
            return False
        except Exception as e:
            log(f"paste failed (wtype): {e}")
            return False
    try:
        kb = KeyController()
        # Tiny delay so the previous Ctrl+Alt+Space release is fully processed
        # before we synthesize Ctrl+V.
        time.sleep(0.08)
        with kb.pressed(Key.ctrl):
            kb.press('v')
            kb.release('v')
        return True
    except Exception as e:
        log(f"paste failed: {e}")
        return False


# ---------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------

class DictateApp:
    STATE_IDLE = "idle"
    STATE_RECORDING = "recording"
    STATE_BUSY = "busy"

    def __init__(self):
        self.state = self.STATE_IDLE
        self._state_lock = threading.Lock()
        self.recorder = Recorder()
        self.backend: Backend | None = None
        self.icon: pystray.Icon | None = None
        self.overlay = RecordingOverlay(self.recorder) if SHOW_OVERLAY else None
        self._indicator: LayerShellIndicator | None = LayerShellIndicator() if not IS_WINDOWS else None
        self._stop_event = threading.Event()

        cfg = load_user_config()
        self.current_model: str = cfg.get("model", MODEL_SIZE)
        if self.current_model not in MODEL_OPTIONS:
            log(f"Persisted model {self.current_model!r} not in MODEL_OPTIONS; falling back to {MODEL_SIZE}")
            self.current_model = MODEL_SIZE

        self.current_hotkey: str = cfg.get("hotkey", HOTKEY)
        if not is_valid_hotkey(self.current_hotkey):
            log(f"Persisted hotkey {self.current_hotkey!r} invalid; falling back to {HOTKEY}")
            self.current_hotkey = HOTKEY

        self.current_cancel_hotkey: str = cfg.get("cancel_hotkey", CANCEL_HOTKEY)
        if not is_valid_hotkey(self.current_cancel_hotkey):
            log(f"Persisted cancel hotkey {self.current_cancel_hotkey!r} invalid; falling back to {CANCEL_HOTKEY}")
            self.current_cancel_hotkey = CANCEL_HOTKEY

        # Inference backend choice. "auto" picks GPU when the bundled
        # whisper.cpp Vulkan binary is present, otherwise CPU.
        self.current_backend: str = cfg.get("backend", BACKEND)
        if self.current_backend not in BACKEND_OPTIONS:
            log(f"Persisted backend {self.current_backend!r} not in BACKEND_OPTIONS; falling back to {BACKEND}")
            self.current_backend = BACKEND

        # Cache GPU availability once at startup so the tray menu can
        # grey out the "GPU" item without re-probing on every rebuild.
        # The probe is cheap (a path existence check); real Vulkan
        # device enumeration happens inside whisper-server at load().
        self._gpu_supported, self._gpu_unavailable_reason = WhisperCppBackend.available()
        if not self._gpu_supported:
            log(f"GPU backend unavailable: {self._gpu_unavailable_reason}")

        # P2: trigger mode -- "toggle" (press to start, press to stop) or
        # "hold" (press-and-hold to record, release to stop).
        self.current_mode: str = cfg.get("mode", "toggle")
        if self.current_mode not in ("toggle", "hold"):
            log(f"Persisted mode {self.current_mode!r} invalid; falling back to toggle")
            self.current_mode = "toggle"

        self.sounds_muted: bool = bool(cfg.get("sounds_muted", False))
        self.sound_preset: str = cfg.get("sound_preset", SOUND_PRESET)
        if self.sound_preset not in SOUND_PRESETS:
            self.sound_preset = "default"
        global _sounds_muted, _current_preset
        _sounds_muted = self.sounds_muted
        _current_preset = self.sound_preset

        self._hotkey_listener = None  # keyboard.GlobalHotKeys or keyboard.Listener
        self._socket_server: socket.socket | None = None  # Linux IPC server
        self._socket_thread: threading.Thread | None = None
        self._hotkey_bound: bool = False
        self._hotkey_last_error: str | None = None

        # Cancel hotkey runs on its own GlobalHotKeys listener so it works in
        # both toggle and hold modes without entangling with the main
        # press/release matcher. Set on cancel-during-busy so the in-flight
        # transcription's result is dropped before clipboard/paste.
        self._cancel_listener = None
        self._cancel_event = threading.Event()

        # Dead-man's switch: forces a stop after MAX_RECORD_SECONDS even if
        # the chord release is missed (relevant for hold mode, but covers
        # toggle too). Guarded by its own lock so arm/cancel/auto-stop don't
        # race on the timer reference under rapid start-stop-start cycles.
        self._max_record_timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()

        # Auto-update state. Populated by the background check; consumed by
        # the tray "Install update..." menu item.
        self._pending_update: "tuple[str, str, str | None] | None" = None  # (version, url, sha256)
        self._update_in_flight: bool = False

    def _save_config(self) -> None:
        save_user_config({
            "model":         self.current_model,
            "hotkey":        self.current_hotkey,
            "cancel_hotkey": self.current_cancel_hotkey,
            "mode":          self.current_mode,
            "backend":       self.current_backend,
            "sounds_muted":  self.sounds_muted,
            "sound_preset":  self.sound_preset,
        })

    # -- model -------------------------------------------------------

    def _resolve_backend_class(self) -> type[Backend]:
        """Map ``self.current_backend`` ("auto"/"gpu"/"cpu") to a concrete
        backend class. Auto picks GPU when the bundled binary is present.
        """
        if self.current_backend == "cpu":
            return FasterWhisperBackend
        if self.current_backend == "gpu":
            return WhisperCppBackend
        # "auto"
        return WhisperCppBackend if self._gpu_supported else FasterWhisperBackend

    def _instantiate_backend(self, cls: type[Backend]) -> Backend:
        if cls is FasterWhisperBackend:
            return FasterWhisperBackend(
                compute_type=COMPUTE_TYPE,
                cpu_threads=CPU_THREADS,
                log=log,
            )
        if cls is WhisperCppBackend:
            return WhisperCppBackend(log=log)
        raise ValueError(f"Unknown backend class: {cls!r}")

    def load_model(self, name: str | None = None) -> None:
        target = name or self.current_model
        desired_cls = self._resolve_backend_class()

        # Reuse the existing backend if it's the right type; otherwise
        # tear it down and build a new one. Reusing matters for the CPU
        # path (CTranslate2 holds native memory) and for the GPU path
        # (we'd otherwise spawn whisper-server twice in quick succession).
        if self.backend is None or not isinstance(self.backend, desired_cls):
            if self.backend is not None:
                try:
                    self.backend.unload()
                except Exception as e:
                    log(f"Previous backend unload error (ignored): {e}")
            self.backend = self._instantiate_backend(desired_cls)

        log(f"Loading model {target} on {self.backend.label} ...")
        try:
            self.backend.load(target)
        except Exception as e:
            # Auto-mode falls back to CPU if GPU load fails (driver issue,
            # no Vulkan device, model file download failure, etc.).
            # Explicit "gpu" propagates the error so the user sees what's
            # wrong instead of silently switching.
            gpu_missing = not self._gpu_supported  # binary absent — not a user error
            if isinstance(self.backend, WhisperCppBackend) and (
                self.current_backend == "auto" or gpu_missing
            ):
                if gpu_missing:
                    notify_error(APP_NAME, "GPU binary not found — using CPU backend.")
                log(f"GPU load failed, falling back to CPU: {e}")
                try:
                    self.backend.unload()
                except Exception as unload_err:
                    log(f"GPU unload during fallback failed (ignored): {unload_err}")
                cpu_backend = self._instantiate_backend(FasterWhisperBackend)
                try:
                    cpu_backend.load(target)
                except Exception as cpu_err:
                    self.backend = None
                    raise RuntimeError(
                        f"GPU failed ({e}); CPU fallback also failed: {cpu_err}"
                    ) from cpu_err
                self.backend = cpu_backend
            else:
                raise

        self.current_model = target
        log(f"Model {target} loaded on {self.backend.label}.")

    def set_model(self, name: str) -> None:
        """Tray callback: switch model on a background thread."""
        if name == self.current_model:
            return
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before switching models.")
                return
            self.state = self.STATE_BUSY  # block toggles during reload
        # Optimistically update so the radio dot moves immediately.
        self.current_model = name
        self._save_config()
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        threading.Thread(target=self._reload_model, args=(name,), daemon=True).start()

    def set_backend(self, choice: str) -> None:
        """Tray callback: switch inference backend on a background thread.

        Mirrors set_model's flow -- block during the swap, persist the
        choice optimistically, then reload the current model under the
        new backend on a worker thread.
        """
        if choice not in BACKEND_OPTIONS or choice == self.current_backend:
            return
        if choice == "gpu" and not self._gpu_supported:
            notify_error(APP_NAME, f"GPU backend unavailable: {self._gpu_unavailable_reason}")
            return
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before switching backends.")
                return
            self.state = self.STATE_BUSY
        self.current_backend = choice
        self._save_config()
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        threading.Thread(target=self._reload_model, args=(self.current_model,), daemon=True).start()

    def _reload_model(self, name: str) -> None:
        self._set_icon(ICON_BUSY, f"{APP_NAME} - loading {name}...")
        try:
            self.load_model(name)
            play_sound("start")  # short audible "ready" cue
        except Exception as e:
            log(f"Model swap failed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Model load failed: {e}")
        finally:
            with self._state_lock:
                if self.state == self.STATE_BUSY:
                    self.state = self.STATE_IDLE
            self._set_icon(ICON_IDLE, f"{APP_NAME} - idle ({self.current_model})")

    # -- hotkey ------------------------------------------------------

    def _start_hotkey_listener(self) -> None:
        """Stop any existing listener and start a fresh one bound to current_hotkey.

        Dispatches to the toggle or hold backend based on `current_mode`.
        On failure, marks `_hotkey_bound=False` and degrades the tray tooltip.
        """
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception as e:
                log(f"Stop old hotkey listener failed: {e}")
            self._hotkey_listener = None
        if not IS_WINDOWS:
            # On Linux the compositor (e.g. niri) owns the keybind.
            # The app exposes a Unix socket; ariasstt-toggle drives on_toggle.
            self._start_socket_listener()
            return
        try:
            if self.current_mode == "hold":
                listener = self._build_hold_listener(self.current_hotkey)
            else:
                listener = keyboard.GlobalHotKeys({self.current_hotkey: self.on_toggle})
            listener.start()
            self._hotkey_listener = listener
            self._hotkey_bound = True
            self._hotkey_last_error = None
            log(f"Hotkey listener bound: mode={self.current_mode} chord={self.current_hotkey}")
            self._refresh_tooltip()
        except Exception as e:
            self._hotkey_bound = False
            self._hotkey_last_error = str(e)
            log(f"Hotkey listener crashed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Hotkey error: {e}")
            self._refresh_tooltip()
        self._start_cancel_listener()

    def _start_cancel_listener(self) -> None:
        """(Re)bind the cancel hotkey listener. Skipped when the cancel chord
        collides with the main hotkey, since both listeners would otherwise
        fire on the same press."""
        if self._cancel_listener is not None:
            try:
                self._cancel_listener.stop()
            except Exception as e:
                log(f"Stop old cancel listener failed: {e}")
            self._cancel_listener = None
        if self.current_cancel_hotkey == self.current_hotkey:
            log(f"Cancel hotkey matches main hotkey ({self.current_hotkey!r}); cancel disabled")
            return
        try:
            listener = keyboard.GlobalHotKeys(
                {self.current_cancel_hotkey: self.on_cancel}
            )
            listener.start()
            self._cancel_listener = listener
            log(f"Cancel hotkey listener bound: {self.current_cancel_hotkey}")
        except Exception as e:
            log(f"Cancel hotkey listener failed: {e}\n{traceback.format_exc()}")

    def _build_hold_listener(self, spec: str) -> "keyboard.Listener":
        """Build a `keyboard.Listener` driving a _HoldChord matcher."""
        keys = keyboard.HotKey.parse(spec)
        chord = _HoldChord(keys, self._on_hold_press, self._on_hold_release)
        listener_holder: list = [None]

        def on_press(key):
            l = listener_holder[0]
            if l is not None:
                chord.press(l.canonical(key))

        def on_release(key):
            l = listener_holder[0]
            if l is not None:
                chord.release(l.canonical(key))

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener_holder[0] = listener
        return listener

    def _on_hold_press(self) -> None:
        """Hold-mode: chord engaged -> start recording (if idle)."""
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                log(f"Hold-press ignored: state={self.state}")
                return
            self.state = self.STATE_RECORDING
        self._start_recording()

    def _on_hold_release(self) -> None:
        """Hold-mode: chord released -> stop and transcribe (if recording)."""
        with self._state_lock:
            if self.state != self.STATE_RECORDING:
                log(f"Hold-release ignored: state={self.state}")
                return
            self.state = self.STATE_BUSY
        self._stop_and_transcribe()

    def _socket_path(self) -> str:
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        return os.path.join(runtime, "ariasstt.sock")

    def _start_socket_listener(self) -> None:
        """Listen on a Unix domain socket for IPC commands from ariasstt-toggle.

        On Linux the compositor (e.g. niri) owns the global keybind and spawns
        ``ariasstt-toggle`` on F9; that script connects here and sends "toggle".
        Supported commands: toggle, cancel, quit, status.
        """
        if self._socket_server is not None:
            try:
                self._socket_server.close()
            except Exception:
                pass
            self._socket_server = None
        sock_path = self._socket_path()
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(sock_path)
            srv.listen(5)
        except Exception as e:
            srv.close()
            self._hotkey_bound = False
            self._hotkey_last_error = str(e)
            log(f"Socket listener failed to bind {sock_path}: {e}")
            notify_error(APP_NAME, f"Socket bind failed: {e}")
            self._refresh_tooltip()
            return
        self._socket_server = srv
        self._hotkey_bound = True
        self._hotkey_last_error = None
        log(f"Socket listener bound: {sock_path}")
        self._refresh_tooltip()

        def _serve() -> None:
            srv.settimeout(0.5)
            while not self._stop_event.is_set():
                # A rebind (set_mode / set_hotkey) or quit() replaces/closes
                # self._socket_server. When that happens, THIS generation of the
                # loop must exit instead of spinning on a dead fd.
                if self._socket_server is not srv:
                    break
                try:
                    try:
                        conn, _ = srv.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        # Socket closed underneath us (rebind/quit) -> exit.
                        break
                    with conn:
                        cmd = conn.recv(64).decode("utf-8", "replace").strip()
                        log(f"Socket command: {cmd!r}")
                        if cmd == "toggle":
                            self.on_toggle()
                        elif cmd == "cancel":
                            self.on_cancel()
                        elif cmd == "quit":
                            self.quit()
                        elif cmd == "status":
                            conn.sendall(self.state.encode("utf-8"))
                except Exception as e:
                    if not self._stop_event.is_set():
                        log(f"Socket server error: {e}")

        self._socket_thread = threading.Thread(
            target=_serve, daemon=True, name="socket-ipc"
        )
        self._socket_thread.start()

    def set_mode(self, mode: str) -> None:
        """Tray callback: switch between toggle and hold modes."""
        if not IS_WINDOWS:
            # Hold mode needs a key-down/key-up listener the app doesn't own on
            # Wayland (the compositor sends a single "toggle"). Don't pretend.
            notify(APP_NAME, "Hold mode is Windows-only; Linux uses the compositor keybind.")
            return
        if mode == self.current_mode:
            return
        if mode not in ("toggle", "hold"):
            notify_error(APP_NAME, f"Unknown mode: {mode}")
            return
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before switching modes.")
                return
        self.current_mode = mode
        self._save_config()
        self._start_hotkey_listener()
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        log(f"Mode set to {mode}")
        notify(APP_NAME, f"Mode: {mode}")

    def _refresh_tooltip(self) -> None:
        """Update tray tooltip based on listener health + current model."""
        if self.icon is None:
            return
        if self._hotkey_bound:
            self.icon.title = f"{APP_NAME} - idle ({self.current_model})"
        else:
            err = self._hotkey_last_error or "unknown"
            err_short = err if len(err) <= 60 else err[:57] + "..."
            self.icon.title = f"{APP_NAME} - ⚠ hotkey error: {err_short}"

    def set_hotkey(self, spec: str) -> None:
        spec = (spec or "").strip()
        if not spec or spec == self.current_hotkey:
            return
        if not is_valid_hotkey(spec):
            notify_error(APP_NAME, f"Invalid hotkey: {spec}")
            return
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before changing hotkey.")
                return
        # P3: best-effort RegisterHotKey conflict probe. Non-blocking -- a
        # claimed combo may still work via the LL hook, and conversely an
        # available probe doesn't rule out hook-swallow conflicts.
        available, msg = probe_hotkey_conflict(spec)
        if not available:
            log(f"Conflict probe: {spec} -> {msg}")
            notify_error(APP_NAME, f"⚠ {spec}: {msg}. Combo may be unreliable.")
        elif msg:
            log(f"Conflict probe inconclusive for {spec}: {msg}")
        self.current_hotkey = spec
        self._save_config()
        self._start_hotkey_listener()
        if self.icon is not None:
            try:
                self.icon.update_menu()
                self.icon.title = f"{APP_NAME} - idle ({self.current_model})"
            except Exception:
                pass
        log(f"Hotkey set to {spec}")
        notify(APP_NAME, f"Hotkey: {spec}")

    def _prompt_custom_hotkey(self) -> None:
        """Open the live key-capture dialog on a dedicated thread (own tk.Tk root)."""
        def _worker():
            try:
                HotkeyCaptureDialog(self).run()
            except Exception as e:
                log(f"Hotkey prompt failed: {e}\n{traceback.format_exc()}")
                notify_error(APP_NAME, f"Hotkey prompt failed: {e}")
        threading.Thread(target=_worker, daemon=True, name="hotkey-prompt").start()

    def test_hotkey(self) -> None:
        """Tray callback: arm a one-shot listener for 5s and report whether the
        bound hotkey is delivered. Catches WH_KEYBOARD_LL hook-swallow conflicts
        that the RegisterHotKey probe can't see (Teams, Discord, Outlook)."""
        threading.Thread(
            target=self._do_test_hotkey, daemon=True, name="hotkey-test"
        ).start()

    # -- auto-update -------------------------------------------------

    def _start_update_check(self) -> None:
        """Schedule a one-shot background check after the app has settled.

        Only runs when bundled (sys.frozen). Skipped in dev so we don't
        nag ourselves with prompts to install over our own venv setup.
        """
        if not getattr(sys, "frozen", False):
            log("Update check skipped: running unfrozen (dev mode).")
            return
        timer = threading.Timer(UPDATE_CHECK_DELAY_S, self._check_update_worker)
        timer.daemon = True
        timer.start()

    def _check_update_worker(self) -> None:
        try:
            result = check_for_update()
        except urllib.error.URLError as e:
            log(f"Update check: network error: {e}")
            return
        except Exception as e:
            log(f"Update check failed: {e}\n{traceback.format_exc()}")
            return
        if result is None:
            log(f"Update check: up to date (current v{__version__}).")
            return
        version, url, _sha = result
        self._pending_update = result
        log(f"Update available: v{version} -> {url}" + ("" if _sha else " (no sha256 sidecar)"))
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        notify_force(APP_NAME, f"Update available: v{version}. Tray menu → Install update.")

    def install_update(self) -> None:
        """Tray callback: download the latest installer and run it silently."""
        if self._pending_update is None or self._update_in_flight:
            return
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before updating.")
                return
        self._update_in_flight = True
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass
        threading.Thread(
            target=self._do_install_update, daemon=True, name="update-install",
        ).start()

    def _do_install_update(self) -> None:
        assert self._pending_update is not None
        version, url, expected_sha = self._pending_update
        try:
            notify_force(APP_NAME, f"Downloading update v{version}...", timeout=3)
            log(f"Downloading update v{version} from {url}")
            tmp_dir = tempfile.gettempdir()
            installer_path = os.path.join(
                tmp_dir, f"Auritus-Setup-v{version}.exe",
            )
            actual_sha = download_installer(url, installer_path)
            log(f"Installer downloaded: {installer_path} sha256={actual_sha}")

            if expected_sha:
                if actual_sha.lower() != expected_sha.lower():
                    log(f"Installer sha256 MISMATCH: expected {expected_sha}, got {actual_sha}; aborting.")
                    notify_error(APP_NAME, "Update aborted: installer failed its integrity check.")
                    try:
                        os.remove(installer_path)
                    except OSError:
                        pass
                    return
                log("Installer sha256 verified against release sidecar.")
            else:
                log("No sha256 sidecar published for this release; proceeding (hash logged above).")

            notify_force(
                APP_NAME,
                f"Installing v{version}. App will restart.",
                timeout=4,
            )
            time.sleep(1.0)
            # /SILENT shows progress without prompts; /SUPPRESSMSGBOXES auto-OKs
            # any dialogs; /CLOSEAPPLICATIONS lets installer kill us;
            # /RESTARTAPPLICATIONS relaunches the new exe after install.
            subprocess.Popen(
                [
                    installer_path,
                    "/SILENT",
                    "/SUPPRESSMSGBOXES",
                    "/CLOSEAPPLICATIONS",
                    "/RESTARTAPPLICATIONS",
                ],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                close_fds=True,
            )
            # Don't quit ourselves -- the installer's CloseApplications handler
            # will close us cleanly. Sleep a moment to give it the handle.
            time.sleep(2.0)
        except Exception as e:
            log(f"Update install failed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Update failed: {e}")
        finally:
            self._update_in_flight = False
            if self.icon is not None:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

    def _do_test_hotkey(self) -> None:
        if not IS_WINDOWS:
            notify_force(APP_NAME, "Hotkey test: compositor handles the keybind on Linux. Trigger via ariasstt-toggle.")
            return
        spec = self.current_hotkey
        pretty = spec.replace("<", "").replace(">", "")

        # Claim BUSY for the duration so the tray "Toggle dictation" item and
        # the on_toggle hotkey path can't fire mid-test. set_mode/set_hotkey
        # already check STATE_IDLE so they'll bail too.
        with self._state_lock:
            if self.state != self.STATE_IDLE:
                notify_error(APP_NAME, "Finish current dictation before testing.")
                return
            self.state = self.STATE_BUSY

        log(f"Test hotkey armed: {spec}")
        notify_force(APP_NAME, f"Press {pretty} now (5s)...")

        main_was_bound = self._hotkey_bound
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception as e:
                log(f"Stop main listener for test failed: {e}")
            self._hotkey_listener = None
            self._hotkey_bound = False

        detected = threading.Event()
        t0 = time.time()
        test_failed = False
        try:
            try:
                test_listener = keyboard.GlobalHotKeys({spec: detected.set})
                test_listener.start()
                try:
                    detected.wait(timeout=5.0)
                finally:
                    try:
                        test_listener.stop()
                    except Exception as e:
                        log(f"Stop test listener failed: {e}")
            except Exception as e:
                test_failed = True
                log(f"Test listener crashed: {e}\n{traceback.format_exc()}")
                notify_error(APP_NAME, f"Test failed: {e}")

            if not test_failed:
                elapsed_ms = int((time.time() - t0) * 1000)
                if detected.is_set():
                    log(f"Test hotkey: detected in {elapsed_ms} ms")
                    notify_force(APP_NAME, f"✓ {pretty} detected ({elapsed_ms} ms)")
                else:
                    log(f"Test hotkey: {spec} not received within 5s")
                    notify_error(
                        APP_NAME,
                        f"✗ {pretty} not received within 5s — likely swallowed by another app",
                    )
        finally:
            with self._state_lock:
                # Only revert if we still own BUSY -- something pathological
                # (e.g. a model swap) might have transitioned away.
                if self.state == self.STATE_BUSY:
                    self.state = self.STATE_IDLE
            # Skip listener restart on quit so we don't spawn an orphan.
            if main_was_bound and not self._stop_event.is_set():
                self._start_hotkey_listener()

    # -- mic check ---------------------------------------------------

    def check_mic(self) -> bool:
        try:
            devs = sd.query_devices()
            inputs = [d for d in devs if d.get("max_input_channels", 0) > 0]
            if not inputs:
                notify(APP_NAME, "No input device found. Plug in a microphone.")
                log("No input devices found.")
                return False
            if MIC_DEVICE is not None:
                # Validate configured device
                try:
                    sd.check_input_settings(device=MIC_DEVICE, samplerate=SAMPLE_RATE, channels=1)
                except Exception as e:
                    notify(APP_NAME, f"Configured mic not usable: {e}")
                    log(f"Mic check failed for device {MIC_DEVICE!r}: {e}")
                    return False
            return True
        except Exception as e:
            notify(APP_NAME, f"Audio system error: {e}")
            log(f"Audio system error: {e}")
            return False

    # -- state -------------------------------------------------------

    def _set_icon(self, image: Image.Image, tooltip: str) -> None:
        if self.icon is not None:
            self.icon.icon = image
            self.icon.title = tooltip

    # -- toggle ------------------------------------------------------

    def on_toggle(self) -> None:
        with self._state_lock:
            if self.state == self.STATE_BUSY:
                log("Toggle ignored: still transcribing.")
                return
            if self.state == self.STATE_IDLE:
                self.state = self.STATE_RECORDING
                start_now = True
            else:
                self.state = self.STATE_BUSY
                start_now = False

        if start_now:
            self._start_recording()
        else:
            self._stop_and_transcribe()

    def on_cancel(self) -> None:
        """Cancel hotkey callback.

        - idle: no-op.
        - recording: stop mic, discard audio, return to idle.
        - busy (transcribing): set the cancel event so `_do_transcribe`
          drops the result before clipboard / paste. Inference still runs
          to completion -- faster-whisper has no interrupt API and aborting
          the whisper-server HTTP call would just leave a half-warmed
          process behind.
        """
        with self._state_lock:
            if self.state == self.STATE_IDLE:
                log("Cancel ignored: idle.")
                return
            if self.state == self.STATE_RECORDING:
                self.state = self.STATE_BUSY  # block toggle during teardown
                cancel_recording = True
            else:
                cancel_recording = False

        if cancel_recording:
            self._cancel_recording()
        else:
            self._cancel_event.set()
            log("Cancel requested during transcription; result will be dropped.")

    def _cancel_recording(self) -> None:
        self._cancel_max_record_timer()
        try:
            self.recorder.stop()  # discard the audio buffer
        except Exception as e:
            log(f"Recorder stop during cancel failed: {e}")
        play_sound("stop")
        log("Recording cancelled.")
        with self._state_lock:
            self.state = self.STATE_IDLE
        self._set_icon(ICON_IDLE, f"{APP_NAME} - idle ({self.current_model})")
        if self.overlay is not None:
            self.overlay.hide()
        if self._indicator is not None:
            self._indicator.hide()

    def _start_recording(self) -> None:
        self._cancel_event.clear()
        try:
            self.recorder.start()
        except Exception as e:
            log(f"Failed to start recording: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Mic start failed: {e}")
            with self._state_lock:
                self.state = self.STATE_IDLE
            self._set_icon(ICON_IDLE, f"{APP_NAME} - idle ({self.current_model})")
            if self.overlay is not None:
                self.overlay.hide()
            return
        self._set_icon(ICON_RECORDING, f"{APP_NAME} - recording")
        if self.overlay is not None:
            self.overlay.show("recording")
        if self._indicator is not None:
            self._indicator.show("recording")
        play_sound("start")
        log("Recording started.")
        # Dead-man's switch: force a stop after MAX_RECORD_SECONDS so a missed
        # release in hold mode (or a forgotten toggle) can't run forever.
        self._arm_max_record_timer()

    def _arm_max_record_timer(self) -> None:
        with self._timer_lock:
            self._cancel_max_record_timer_locked()
            timer = threading.Timer(MAX_RECORD_SECONDS, self._auto_stop)
            timer.daemon = True
            timer.start()
            self._max_record_timer = timer

    def _cancel_max_record_timer(self) -> None:
        with self._timer_lock:
            self._cancel_max_record_timer_locked()

    def _cancel_max_record_timer_locked(self) -> None:
        t = self._max_record_timer
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
            self._max_record_timer = None

    def _auto_stop(self) -> None:
        with self._state_lock:
            if self.state != self.STATE_RECORDING:
                return
            self.state = self.STATE_BUSY
        log(f"Auto-stop after MAX_RECORD_SECONDS={MAX_RECORD_SECONDS}")
        notify_force(APP_NAME, f"Auto-stopped after {MAX_RECORD_SECONDS}s")
        self._stop_and_transcribe()

    def _stop_and_transcribe(self) -> None:
        self._set_icon(ICON_BUSY, f"{APP_NAME} - transcribing")
        if self.overlay is not None:
            self.overlay.set_state("transcribing")
        if self._indicator is not None:
            self._indicator.show("transcribing")
        # Run on a worker thread so the hotkey listener stays responsive.
        threading.Thread(target=self._do_transcribe, daemon=True).start()

    def _do_transcribe(self) -> None:
        self._cancel_max_record_timer()
        try:
            audio = self.recorder.stop()
            duration = len(audio) / SAMPLE_RATE if len(audio) else 0.0
            log(f"Recording stopped: {duration:.2f}s, {len(audio)} samples")

            if self._cancel_event.is_set():
                play_sound("stop")
                log("Transcription cancelled before inference; audio dropped.")
                return

            if duration < 0.25:
                play_sound("stop")
                log("Recording too short, ignored.")
                return

            t0 = time.time()
            text = self._transcribe(audio)
            log(f"Inference took {time.time() - t0:.2f}s ({self.current_model})")
            text = clean_text(text)

            if self._cancel_event.is_set():
                play_sound("stop")
                log(f"Transcription cancelled; dropping {len(text)} chars.")
                return

            if not text:
                play_sound("stop")
                log("Empty transcription.")
                return

            if DEBUG_LOG_TEXT:
                log(f"Transcribed: {text!r}")
            else:
                log(f"Transcribed {len(text)} chars.")

            try:
                pyperclip.copy(text)
            except Exception as e:
                notify_error(APP_NAME, f"Clipboard copy failed: {e}")
                return

            if AUTO_PASTE:
                ok = paste_clipboard(text)
                if not ok:
                    notify_error(APP_NAME, "Paste failed; text is on the clipboard.")
            play_sound("stop")

        except Exception as e:
            log(f"Transcription pipeline failed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Transcription failed: {e}")
        finally:
            with self._state_lock:
                self.state = self.STATE_IDLE
            self._set_icon(ICON_IDLE, f"{APP_NAME} - idle ({self.current_model})")
            if self.overlay is not None:
                self.overlay.hide()
            if self._indicator is not None:
                self._indicator.hide()

    def _transcribe(self, audio: np.ndarray) -> str:
        # The active backend handles dtype, VAD, and language selection
        # internally -- callers just hand it the raw 16 kHz mono buffer
        # produced by Recorder.stop().
        if self.backend is None:
            raise RuntimeError("_transcribe called before a backend was loaded")
        try:
            return self.backend.transcribe(audio)
        except Exception as e:
            # The GPU server can fail a single inference even after its own
            # retry (see WhisperCppBackend.transcribe). Rather than lose the
            # user's captured speech, transcribe this one utterance on CPU.
            # The persistent backend is left untouched so the next dictation
            # goes back to GPU.
            if not isinstance(self.backend, WhisperCppBackend):
                raise
            log(f"GPU transcription failed; CPU fallback for this utterance: {e}")
            cpu = FasterWhisperBackend(
                compute_type=COMPUTE_TYPE,
                cpu_threads=CPU_THREADS,
                log=log,
            )
            cpu.load(self.current_model)
            try:
                return cpu.transcribe(audio)
            finally:
                cpu.unload()

    # -- tray --------------------------------------------------------

    def _model_submenu(self) -> pystray.Menu:
        items = []
        for name in MODEL_OPTIONS:
            items.append(pystray.MenuItem(
                name,
                (lambda n: lambda icon, item: self.set_model(n))(name),
                checked=(lambda n: lambda item: self.current_model == n)(name),
                radio=True,
            ))
        return pystray.Menu(*items)

    def _backend_submenu(self) -> pystray.Menu:
        labels = {
            "auto": "Auto (GPU when available)",
            "gpu":  "GPU (whisper.cpp Vulkan)",
            "cpu":  "CPU (faster-whisper)",
        }
        items = []
        for name in BACKEND_OPTIONS:
            label = labels[name]
            if name == "gpu" and not self._gpu_supported:
                label = f"{labels[name]}  (unavailable)"
            items.append(pystray.MenuItem(
                label,
                (lambda n: lambda icon, item: self.set_backend(n))(name),
                checked=(lambda n: lambda item: self.current_backend == n)(name),
                radio=True,
                enabled=(lambda n: lambda item: not (n == "gpu" and not self._gpu_supported))(name),
            ))
        return pystray.Menu(*items)

    def _hotkey_submenu(self) -> pystray.Menu:
        preset_specs = {spec for spec, _ in HOTKEY_PRESETS}
        items = []
        for spec, warn in HOTKEY_PRESETS:
            label = spec if not warn else f"{spec}  ⚠  {warn}"
            items.append(pystray.MenuItem(
                label,
                (lambda s: lambda icon, item: self.set_hotkey(s))(spec),
                checked=(lambda s: lambda item: self.current_hotkey == s)(spec),
                radio=True,
            ))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(
            lambda item: (
                f"Custom... ({self.current_hotkey})"
                if self.current_hotkey not in preset_specs
                else "Custom..."
            ),
            lambda icon, item: self._prompt_custom_hotkey(),
            checked=lambda item: self.current_hotkey not in preset_specs,
            radio=True,
        ))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(
            "Test hotkey...",
            lambda icon, item: self.test_hotkey(),
        ))
        return pystray.Menu(*items)

    def _mode_submenu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Toggle (press to start, press to stop)",
                lambda icon, item: self.set_mode("toggle"),
                checked=lambda item: self.current_mode == "toggle",
                radio=True,
            ),
            pystray.MenuItem(
                "Hold (press-and-hold to record)",
                lambda icon, item: self.set_mode("hold"),
                checked=lambda item: self.current_mode == "hold",
                radio=True,
            ),
        )

    def set_sounds_muted(self, muted: bool) -> None:
        global _sounds_muted
        self.sounds_muted = muted
        _sounds_muted = muted
        self._save_config()
        log(f"Sounds {'muted' if muted else 'unmuted'}")

    def set_sound_preset(self, preset: str) -> None:
        global _current_preset
        if preset not in SOUND_PRESETS:
            return
        self.sound_preset = preset
        _current_preset = preset
        self._save_config()
        log(f"Sound preset: {preset}")
        play_sound("start")

    def _sound_submenu(self) -> pystray.Menu:
        items: list = [
            pystray.MenuItem(
                "Mute",
                lambda icon, item: self.set_sounds_muted(not self.sounds_muted),
                checked=lambda item: self.sounds_muted,
            ),
            pystray.Menu.SEPARATOR,
        ]
        for name in SOUND_PRESETS:
            items.append(pystray.MenuItem(
                name.capitalize(),
                (lambda n: lambda icon, item: self.set_sound_preset(n))(name),
                checked=(lambda n: lambda item: self.sound_preset == n)(name),
                radio=True,
                enabled=lambda item: not self.sounds_muted,
            ))
        items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Test sound",
                lambda icon, item: (
                    play_sound("start"),
                    threading.Timer(0.6, lambda: play_sound("stop")).start(),
                ),
            ),
        ])
        return pystray.Menu(*items)

    def _build_menu(self) -> pystray.Menu:
        def toggle_label(_item):
            if self.current_mode == "hold":
                return f"Toggle dictation (hold mode — use {self.current_hotkey})"
            return f"Toggle dictation ({self.current_hotkey})"

        return pystray.Menu(
            pystray.MenuItem(
                toggle_label,
                lambda icon, item: self.on_toggle(),
                default=True,
                enabled=lambda item: self.current_mode == "toggle",
            ),
            pystray.MenuItem("Mode", self._mode_submenu(), visible=lambda item: IS_WINDOWS),
            pystray.MenuItem("Model", self._model_submenu()),
            pystray.MenuItem("Backend", self._backend_submenu()),
            pystray.MenuItem("Hotkey", self._hotkey_submenu()),
            pystray.MenuItem("Sound", self._sound_submenu()),
            pystray.MenuItem(
                "Open log folder",
                lambda icon, item: (
                    os.startfile(str(LOG_PATH.parent)) if IS_WINDOWS  # type: ignore[attr-defined]
                    else subprocess.Popen(["xdg-open", str(LOG_PATH.parent)], start_new_session=True)
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: (
                    f"⬇ Installing v{self._pending_update[0]}..."
                    if self._update_in_flight and self._pending_update
                    else (
                        f"⬇ Install update v{self._pending_update[0]}"
                        if self._pending_update
                        else "Update"
                    )
                ),
                lambda icon, item: self.install_update(),
                visible=lambda item: self._pending_update is not None,
                enabled=lambda item: not self._update_in_flight,
            ),
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Auritus v{__version__}", None, enabled=False),
        )

    def quit(self) -> None:
        log("Quit requested.")
        self._stop_event.set()
        self._cancel_max_record_timer()
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None
        if self._cancel_listener is not None:
            try:
                self._cancel_listener.stop()
            except Exception:
                pass
            self._cancel_listener = None
        if self._socket_server is not None:
            try:
                self._socket_server.close()
            except Exception:
                pass
            try:
                os.unlink(self._socket_path())
            except Exception:
                pass
            self._socket_server = None
        try:
            self.recorder.stop()
        except Exception:
            pass
        if self.overlay is not None:
            self.overlay.stop()
        if self._indicator is not None:
            self._indicator.stop()
        if self.backend is not None:
            try:
                self.backend.unload()
            except Exception:
                pass
        if self.icon is not None:
            self.icon.stop()

    # -- run ---------------------------------------------------------

    def run(self) -> None:
        log(f"=== {APP_NAME} starting ===")
        if self.overlay is not None:
            try:
                self.overlay.start()
            except Exception as e:
                log(f"overlay start failed (continuing without it): {e}")
                self.overlay = None
        if not self.check_mic():
            # Continue running so the user sees the tray icon and the log,
            # but they will hit the same error when toggling.
            log("Continuing despite mic check failure; toggle will retry.")

        # Show the tray icon BEFORE loading the model. On first run the model
        # is a one-time ~1.5 GB download; loading it inline here would leave the
        # process alive with no tray presence for minutes, which reads as a hang.
        # The model loads on a worker thread (_startup_load), which flips the
        # icon from "loading" to idle and arms the hotkey once it's ready.
        with self._state_lock:
            self.state = self.STATE_BUSY  # block toggles until the model is ready
        self.icon = pystray.Icon(
            APP_NAME,
            ICON_BUSY,
            f"{APP_NAME} - loading {self.current_model}...",
            self._build_menu(),
        )
        # Kick off the GitHub Releases poll (skipped in dev / unfrozen).
        self._start_update_check()
        threading.Thread(target=self._startup_load, daemon=True).start()
        self.icon.run()
        log(f"=== {APP_NAME} stopped ===")

    def _startup_load(self) -> None:
        """Load the model on a worker thread so the tray icon shows immediately.

        On first run the model is a one-time ~1.5 GB download; loading it inline
        in run() would leave the process alive with no tray icon for minutes,
        which looks like a hang. We display a "loading" icon right away, load
        here, then flip to idle and arm the hotkey once the model is ready.
        """
        notify_force(
            APP_NAME,
            f"Setting up the {self.current_model} model "
            "(one-time ~1.5 GB download on first run)...",
        )
        try:
            self.load_model()
        except Exception as e:
            log(f"Initial model load failed: {e}\n{traceback.format_exc()}")
            self._set_icon(ICON_BUSY, f"{APP_NAME} - model load failed (see log)")
            notify_error(APP_NAME, f"Model load failed: {e}")
            return

        self._start_hotkey_listener()
        with self._state_lock:
            if self.state == self.STATE_BUSY:
                self.state = self.STATE_IDLE
        self._set_icon(ICON_IDLE, f"{APP_NAME} - idle ({self.current_model})")
        # Reflect actual listener state in the tooltip (P5).
        self._refresh_tooltip()
        pretty_hotkey = self.current_hotkey.replace('<', '').replace('>', '')
        notify(APP_NAME, f"Ready ({self.current_model}). Press {pretty_hotkey} to dictate.")


def _enable_dpi_awareness() -> None:
    """Tell Windows to give us real (un-scaled) pixels so tkinter, the tray
    icon, and the overlay don't render blurry on high-DPI displays. Tries
    the most modern API first and falls back along the way. Must run before
    any tk window is created, so call this from main() before DictateApp."""
    if not sys.platform.startswith("win"):
        return
    # Win10 1607+: per-monitor v2 (best behavior across mixed-DPI setups).
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        ):
            return
    except Exception:
        pass
    # Win8.1+: per-monitor v1.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    # Vista+: system-DPI aware.
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    _enable_dpi_awareness()
    try:
        DictateApp().run()
    except Exception as e:
        log(f"Fatal: {e}\n{traceback.format_exc()}")
        notify_error(APP_NAME, f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
