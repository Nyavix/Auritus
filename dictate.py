"""
AriasSTT - push-to-talk Whisper dictation tray app for Windows.

Toggle hotkey starts/stops a recording. On stop, audio is transcribed locally
with faster-whisper (CPU), copied to the clipboard, and pasted into the
focused window via Ctrl+V.

Run with `pythonw dictate.py` to suppress the console window.
"""

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

# Show Windows toast notifications. With sounds + overlay enabled you usually
# don't want these, so they're off by default. Errors still get toasted
# regardless of this setting (see notify_error).
SHOW_NOTIFICATIONS = False

# Play a short sound when recording starts and stops.
PLAY_SOUNDS = True

# Optional custom .wav file paths. Leave None to use built-in synthesized tones.
SOUND_START = None  # e.g. r"C:\path\to\start.wav"
SOUND_STOP = None   # e.g. r"C:\path\to\stop.wav"

# Master volume for the built-in synthesized tones (0.0 - 1.0).
SOUND_VOLUME = 0.35

# Show a small always-on-top mic overlay while recording / transcribing.
SHOW_OVERLAY = True

# Overlay position on the primary screen: "top", "bottom", or "top-right".
OVERLAY_POSITION = "top"

# Distance in pixels from the screen edge.
OVERLAY_MARGIN = 40

# Models selectable from the tray menu. Smaller = faster, less accurate.
# Order matters: this is how they appear in the menu.
MODEL_OPTIONS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]

# Number of CPU threads for inference. 0 = let faster-whisper decide.
CPU_THREADS = 0

# =====================================================================

import os
import sys
import re
import io
import json
import time
import queue
import struct
import ctypes
import tempfile
import threading
import traceback
import winsound
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

import pyperclip
from pynput import keyboard
from pynput.keyboard import Controller as KeyController, Key

from PIL import Image, ImageDraw, ImageTk
import pystray
import tkinter as tk

try:
    from plyer import notification as plyer_notification
except Exception:
    plyer_notification = None

from faster_whisper import WhisperModel


APP_NAME = "AriasSTT"
LOG_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME / "ariasstt.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


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
# Persisted user config (model selection)
# ---------------------------------------------------------------------

CONFIG_PATH = LOG_PATH.parent / "config.json"


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
    HOTKEY_ID = 0xA51A  # arbitrary, just needs to be unique within process
    user32 = ctypes.windll.user32
    user32.RegisterHotKey.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
    ]
    user32.RegisterHotKey.restype = ctypes.c_int
    user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.UnregisterHotKey.restype = ctypes.c_int
    ctypes.set_last_error(0)
    ok = user32.RegisterHotKey(None, HOTKEY_ID, mods, vk)
    if not ok:
        err = ctypes.get_last_error()
        ERROR_HOTKEY_ALREADY_REGISTERED = 1409
        if err == ERROR_HOTKEY_ALREADY_REGISTERED:
            return False, "already registered by another app"
        return False, f"RegisterHotKey failed (err={err})"
    user32.UnregisterHotKey(None, HOTKEY_ID)
    return True, ""


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


# Built-in tones: rising for start, falling for stop. Short and gentle.
# Written to disk at module load — winsound's SND_MEMORY path is flaky on
# some Windows audio configs; SND_FILENAME is rock-solid.
_START_WAV_BYTES = _make_wav_tone([(660, 0.06), (990, 0.09)], volume=SOUND_VOLUME)
_STOP_WAV_BYTES  = _make_wav_tone([(880, 0.06), (587, 0.10)], volume=SOUND_VOLUME)


def _write_temp_wav(data: bytes, name: str) -> str | None:
    try:
        path = os.path.join(tempfile.gettempdir(), f"ariasstt_{name}.wav")
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception as e:
        log(f"failed to write temp wav {name}: {e}")
        return None


_START_WAV_PATH = _write_temp_wav(_START_WAV_BYTES, "start")
_STOP_WAV_PATH  = _write_temp_wav(_STOP_WAV_BYTES, "stop")


def _beep_fallback(kind: str) -> None:
    """Last-resort tone via winsound.Beep. Synchronous, run on a worker thread."""
    try:
        if kind == "start":
            winsound.Beep(660, 60); winsound.Beep(990, 90)
        else:
            winsound.Beep(880, 60); winsound.Beep(587, 100)
    except Exception as e:
        log(f"Beep fallback failed: {e}")


def play_sound(kind: str) -> None:
    """kind = 'start' or 'stop'. Always returns immediately."""
    if not PLAY_SOUNDS:
        return

    def _play():
        log(f"play_sound({kind})")
        # 1. Custom user-supplied WAV
        custom = SOUND_START if kind == "start" else SOUND_STOP
        if custom and os.path.isfile(custom):
            try:
                winsound.PlaySound(custom, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception as e:
                log(f"PlaySound({custom}) failed: {e}")

        # 2. Built-in synthesized WAV from temp file
        path = _START_WAV_PATH if kind == "start" else _STOP_WAV_PATH
        if path and os.path.isfile(path):
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception as e:
                log(f"PlaySound({path}) failed: {e}")

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
# Recording overlay (always-on-top mic indicator)
# ---------------------------------------------------------------------

def _make_mic_image(size: int = 36, color=(255, 90, 90, 255)) -> Image.Image:
    """Draw a clean microphone glyph on a transparent background."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size // 2
    cap_w = int(size * 0.32)
    cap_top = int(size * 0.18)
    cap_bot = int(size * 0.62)
    # capsule body
    d.rounded_rectangle(
        [cx - cap_w // 2, cap_top, cx + cap_w // 2, cap_bot],
        radius=cap_w // 2, fill=color,
    )
    # U-shaped stand
    arc_l = cx - int(cap_w * 0.95)
    arc_r = cx + int(cap_w * 0.95)
    arc_t = int(size * 0.42)
    arc_b = int(size * 0.78)
    d.arc([arc_l, arc_t, arc_r, arc_b], start=0, end=180, fill=color, width=3)
    # post
    post_top = int((arc_t + arc_b) / 2)
    post_bot = int(size * 0.88)
    d.line([cx, post_top, cx, post_bot], fill=color, width=3)
    # base
    base_w = int(cap_w * 0.9)
    d.line([cx - base_w // 2, post_bot, cx + base_w // 2, post_bot], fill=color, width=3)
    return img


class RecordingOverlay:
    """Frameless always-on-top window with a mic glyph + status text.

    tkinter must run on its own thread; show()/hide()/set_state() are
    thread-safe and marshal onto that thread via root.after.
    """

    BG = "#1a1a1a"
    TRANSPARENT_KEY = "#010203"  # arbitrary near-black we treat as alpha key

    STATES = {
        "recording":    {"text": "Recording",    "color": (255, 90, 90, 255),  "fg": "#ff6868"},
        "transcribing": {"text": "Transcribing", "color": (240, 200, 90, 255), "fg": "#f0c85a"},
    }

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._root: tk.Tk | None = None
        self._frame: tk.Frame | None = None
        self._icon_label: tk.Label | None = None
        self._text_label: tk.Label | None = None
        self._photos: dict = {}
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="overlay")
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run(self) -> None:
        try:
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.93)
            root.configure(bg=self.BG)
            try:
                root.attributes("-transparentcolor", self.TRANSPARENT_KEY)
            except Exception:
                pass

            frame = tk.Frame(root, bg=self.BG, padx=14, pady=8)
            frame.pack()

            # Pre-render mic glyphs for each state.
            for name, cfg in self.STATES.items():
                pil = _make_mic_image(size=28, color=cfg["color"])
                self._photos[name] = ImageTk.PhotoImage(pil, master=root)

            initial = self.STATES["recording"]
            self._icon_label = tk.Label(frame, image=self._photos["recording"], bg=self.BG)
            self._icon_label.pack(side="left", padx=(0, 10))
            self._text_label = tk.Label(
                frame, text=initial["text"], bg=self.BG, fg=initial["fg"],
                font=("Segoe UI", 11, "bold"),
            )
            self._text_label.pack(side="left")

            self._root = root
            self._frame = frame
            self._ready.set()
            root.mainloop()
        except Exception as e:
            log(f"overlay thread error: {e}\n{traceback.format_exc()}")
            self._ready.set()

    # --- thread-safe public API ---------------------------------------

    def show(self, state: str = "recording") -> None:
        if self._root is None:
            return
        try:
            self._root.after(0, lambda: self._do_show(state))
        except Exception as e:
            log(f"overlay show error: {e}")

    def set_state(self, state: str) -> None:
        if self._root is None:
            return
        try:
            self._root.after(0, lambda: self._do_set_state(state))
        except Exception as e:
            log(f"overlay set_state error: {e}")

    def hide(self) -> None:
        if self._root is None:
            return
        try:
            self._root.after(0, self._do_hide)
        except Exception as e:
            log(f"overlay hide error: {e}")

    def stop(self) -> None:
        if self._root is None:
            return
        try:
            self._root.after(0, self._root.destroy)
        except Exception:
            pass

    # --- runs on overlay thread ---------------------------------------

    def _do_set_state(self, state: str) -> None:
        cfg = self.STATES.get(state)
        if not cfg or self._icon_label is None or self._text_label is None:
            return
        self._icon_label.configure(image=self._photos[state])
        self._text_label.configure(text=cfg["text"], fg=cfg["fg"])

    def _do_show(self, state: str) -> None:
        self._do_set_state(state)
        self._root.update_idletasks()
        self._reposition()
        self._root.deiconify()
        self._root.lift()
        self._root.attributes("-topmost", True)

    def _do_hide(self) -> None:
        self._root.withdraw()

    def _reposition(self) -> None:
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww = max(self._root.winfo_width(), self._root.winfo_reqwidth())
        wh = max(self._root.winfo_height(), self._root.winfo_reqheight())
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
        self._root.geometry(f"+{x}+{y}")


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

def paste_clipboard() -> bool:
    """Send Ctrl+V to the focused window. Returns True on success."""
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
        self.model: WhisperModel | None = None
        self.icon: pystray.Icon | None = None
        self.overlay = RecordingOverlay() if SHOW_OVERLAY else None
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
        self._hotkey_listener: keyboard.GlobalHotKeys | None = None
        self._hotkey_bound: bool = False
        self._hotkey_last_error: str | None = None

    def _save_config(self) -> None:
        save_user_config({"model": self.current_model, "hotkey": self.current_hotkey})

    # -- model -------------------------------------------------------

    def load_model(self, name: str | None = None) -> None:
        target = name or self.current_model
        log(f"Loading model {target} ({COMPUTE_TYPE}) ...")
        kwargs = dict(device="cpu", compute_type=COMPUTE_TYPE)
        if CPU_THREADS > 0:
            kwargs["cpu_threads"] = CPU_THREADS
        self.model = WhisperModel(target, **kwargs)
        self.current_model = target
        log(f"Model {target} loaded.")

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

        On failure, marks `_hotkey_bound=False` and degrades the tray tooltip
        so the user can still rebind via the menu.
        """
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception as e:
                log(f"Stop old hotkey listener failed: {e}")
            self._hotkey_listener = None
        try:
            listener = keyboard.GlobalHotKeys({self.current_hotkey: self.on_toggle})
            listener.start()
            self._hotkey_listener = listener
            self._hotkey_bound = True
            self._hotkey_last_error = None
            log(f"Hotkey listener bound to {self.current_hotkey}")
            self._refresh_tooltip()
        except Exception as e:
            self._hotkey_bound = False
            self._hotkey_last_error = str(e)
            log(f"Hotkey listener crashed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Hotkey error: {e}")
            self._refresh_tooltip()

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

    def _do_test_hotkey(self) -> None:
        spec = self.current_hotkey
        pretty = spec.replace("<", "").replace(">", "")
        log(f"Test hotkey armed: {spec}")
        notify_force(APP_NAME, f"Press {pretty} now (5s)...")

        # Pause main listener so the test press doesn't accidentally trigger
        # a recording. Track whether it was bound so we can restart it cleanly.
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
            log(f"Test listener crashed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Test failed: {e}")
            if main_was_bound:
                self._start_hotkey_listener()
            return

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

        if main_was_bound:
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

    def _start_recording(self) -> None:
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
        play_sound("start")
        log("Recording started.")

    def _stop_and_transcribe(self) -> None:
        self._set_icon(ICON_BUSY, f"{APP_NAME} - transcribing")
        if self.overlay is not None:
            self.overlay.set_state("transcribing")
        # Run on a worker thread so the hotkey listener stays responsive.
        threading.Thread(target=self._do_transcribe, daemon=True).start()

    def _do_transcribe(self) -> None:
        try:
            audio = self.recorder.stop()
            duration = len(audio) / SAMPLE_RATE if len(audio) else 0.0
            log(f"Recording stopped: {duration:.2f}s, {len(audio)} samples")

            if duration < 0.25:
                play_sound("stop")
                log("Recording too short, ignored.")
                return

            t0 = time.time()
            text = self._transcribe(audio)
            log(f"Inference took {time.time() - t0:.2f}s ({self.current_model})")
            text = clean_text(text)
            if not text:
                play_sound("stop")
                log("Empty transcription.")
                return

            log(f"Transcribed: {text!r}")

            try:
                pyperclip.copy(text)
            except Exception as e:
                notify_error(APP_NAME, f"Clipboard copy failed: {e}")
                return

            if AUTO_PASTE:
                ok = paste_clipboard()
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

    def _transcribe(self, audio: np.ndarray) -> str:
        # faster-whisper accepts a numpy float32 array at 16 kHz directly.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        # Normalize peaks to avoid clipping artifacts hurting the model.
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / max(peak, 1.0)

        segments, info = self.model.transcribe(
            audio,
            language="en" if self.current_model.endswith(".en") else None,
            beam_size=1,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text for seg in segments)

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

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Toggle dictation ({self.current_hotkey})",
                lambda icon, item: self.on_toggle(),
                default=True,
            ),
            pystray.MenuItem("Model", self._model_submenu()),
            pystray.MenuItem("Hotkey", self._hotkey_submenu()),
            pystray.MenuItem(
                "Test sound",
                lambda icon, item: (play_sound("start"), threading.Timer(0.6, lambda: play_sound("stop")).start()),
            ),
            pystray.MenuItem(
                "Open log folder",
                lambda icon, item: os.startfile(str(LOG_PATH.parent)),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
        )

    def quit(self) -> None:
        log("Quit requested.")
        self._stop_event.set()
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None
        try:
            self.recorder.stop()
        except Exception:
            pass
        if self.overlay is not None:
            self.overlay.stop()
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

        try:
            self.load_model()
        except Exception as e:
            log(f"Model load failed: {e}\n{traceback.format_exc()}")
            notify_error(APP_NAME, f"Model load failed: {e}")
            return

        self._start_hotkey_listener()

        pretty_hotkey = self.current_hotkey.replace('<', '').replace('>', '')
        notify(APP_NAME, f"Ready ({self.current_model}). Press {pretty_hotkey} to dictate.")

        self.icon = pystray.Icon(
            APP_NAME,
            ICON_IDLE,
            f"{APP_NAME} - idle ({self.current_model})",
            self._build_menu(),
        )
        # Reflect actual listener state in the tooltip (P5).
        self._refresh_tooltip()
        self.icon.run()
        log(f"=== {APP_NAME} stopped ===")


def main():
    try:
        DictateApp().run()
    except Exception as e:
        log(f"Fatal: {e}\n{traceback.format_exc()}")
        notify_error(APP_NAME, f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
