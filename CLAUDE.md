# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Single-machine Windows tray app: push-to-talk Whisper dictation. Hotkey toggles
recording → Whisper inference → text is pasted into the focused window.

Two inference backends coexist:

- **CPU** (`faster-whisper` / CTranslate2) — always available. Default when no
  GPU binary is present.
- **GPU** (`whisper.cpp` Vulkan via `whisper-server.exe`) — Vulkan is
  vendor-agnostic, so it works on AMD (target machine), NVIDIA, and Intel GPUs.
  The `whisper-server.exe` binary is built by CI on tag and bundled into the
  installer. Dev builds without the binary fall back to CPU automatically.

"Auto" mode (default) picks GPU when `whisper-server.exe` is present and a
Vulkan device is found; falls back to CPU otherwise.

There is no test suite, no linter. CI is GitHub Actions (release pipeline only).

## Common commands

All commands assume the repo root as CWD and that `setup.bat` has been run.

| Task | Command |
|---|---|
| First-time install (creates `venv\`, installs deps, downloads `medium.en` model) | `setup.bat` |
| Run with no console window (production) | `venv\Scripts\pythonw dictate.py` |
| Run with console output (debugging — print/log appear in the terminal) | `venv\Scripts\python dictate.py` |
| Register login auto-start | `install_startup.bat` |
| Unregister login auto-start | `uninstall_startup.bat` |
| List audio input devices (for setting `MIC_DEVICE`) | `venv\Scripts\python -m sounddevice` |
| Tail the runtime log | `Get-Content "$env:LOCALAPPDATA\Auritus\auritus.log" -Wait` |

To verify a code change manually: kill any running instance via the tray
(right-click → Quit), launch the console version, exercise the hotkey, and
watch the log lines stream — there is no automated harness.

## Architecture

`dictate.py` is the main app. Top of file is a config block (HOTKEY,
MODEL_SIZE, MIC_DEVICE, sound paths, overlay settings, MODEL_OPTIONS,
BACKEND, BACKEND_OPTIONS, etc.) — **always check the config block first**
when changing user-visible behavior; many settings are intentionally
module-level constants rather than buried in classes.

### Backend abstraction (`backends/`)

```
backends/
  __init__.py               # exports Backend, FasterWhisperBackend, WhisperCppBackend
  base.py                   # Backend ABC: available() / load() / transcribe() / unload()
  faster_whisper_backend.py # CPU path — wraps WhisperModel
  whisper_cpp_backend.py    # GPU path — spawns whisper-server.exe subprocess, HTTP POST WAV
```

`DictateApp` holds `self.backend: Backend | None` (not `self.model`).
`load_model()` calls `self.backend.load(name)`. `_transcribe()` calls
`self.backend.transcribe(audio)`. `quit()` calls `self.backend.unload()`.

`WhisperCppBackend`:
- Resolves `whisper-server.exe` from `vendor/whisper-cpp/` (dev) or
  `sys._MEIPASS/vendor/whisper-cpp/` (bundle).
- Downloads GGUF models to `%LOCALAPPDATA%\Auritus\models\` on first use.
- Spawns `whisper-server.exe` once per `load()` call; keeps it warm.
- Encodes audio as 16-bit PCM WAV via `scipy.io.wavfile` and POSTs to
  the server's `/inference` endpoint (no `requests` dep — stdlib only).

Two model cache locations coexist independently:
- CPU: `%USERPROFILE%\.cache\huggingface\hub` (CTranslate2 format)
- GPU: `%LOCALAPPDATA%\Auritus\models\` (GGUF `.bin` format)

### Threading model (the part that catches you out)

Three separate threads cooperate. Misplacing work between them causes deadlocks
or UI freezes:

1. **Main thread** — runs `pystray.Icon.run()`, which blocks. The tray menu
   callbacks fire here. Do not do long work here.
2. **Hotkey thread** — `pynput.keyboard.GlobalHotKeys` listener. Toggle
   callback (`on_toggle`) runs here. It must return fast: it only flips state
   and dispatches.
3. **Overlay thread** — `tkinter` mainloop for the always-on-top mic
   indicator. tkinter is not thread-safe; the public `RecordingOverlay.show /
   hide / set_state / stop` methods marshal onto this thread via
   `root.after(0, ...)`. Don't call tkinter widgets from anywhere else.
4. **Worker threads (ad-hoc)** — `_do_transcribe` and `_reload_model` are
   spawned per-invocation as daemon threads so inference / model load doesn't
   block the hotkey or the tray.

`DictateApp._state_lock` guards the `state` field (`idle | recording | busy`).
`busy` blocks new toggles during transcription **and** during model swaps.

### State machine

```
idle  --hotkey-->  recording  --hotkey-->  busy  --(transcribe + paste)-->  idle
                                            ^
                                            |
                              set_model() also parks state here while a new
                              model loads, then returns to idle.
```

The model-swap path optimistically updates `current_model` and saves to disk
*before* the load succeeds, so the radio dot in the tray menu moves
immediately. If the load fails, `current_model` is now the failed name; the
inference object (`self.model`) still points at the old one. This is
intentional UX — restart-time fallback handles the persisted-but-broken case
in `__init__` (validates against `MODEL_OPTIONS`).

### Persistence

- **Runtime log:** `%LOCALAPPDATA%\Auritus\auritus.log` (append-only, written
  by `log()`).
- **User config:** `%LOCALAPPDATA%\Auritus\config.json`. Currently only stores
  `{"model": "..."}`. Written by `save_user_config`, read in `__init__`. The
  `MODEL_SIZE` constant in the config block is the *initial* value used only
  if no config file exists.

### Sound and overlay are independent of toasts

Three feedback channels exist and are toggled separately:

- `PLAY_SOUNDS` → `winsound`-played WAV tones (synthesized in-memory at module
  load via `_make_wav_tone`; `SOUND_START` / `SOUND_STOP` override with
  user-supplied `.wav`).
- `SHOW_OVERLAY` → tkinter mic indicator.
- `SHOW_NOTIFICATIONS` → routine plyer toasts. **Default is `False`.** Errors
  bypass this flag via `notify_error()` so the user always sees real failures.

When adding a new feedback event, route it through whichever of these channels
matches its severity — don't add a new channel.

### Why the Startup folder, not Task Scheduler

`install_startup.bat` drops a `.lnk` in `shell:startup`. Task Scheduler launches
GUI apps in a way that frequently breaks tray-icon registration. The Startup
folder runs in the user's interactive desktop session, which is what pystray
needs. Don't switch to Task Scheduler without verifying the tray still appears.

### Paste mechanism

After clipboard copy, `paste_clipboard()` synthesizes Ctrl+V via pynput. The
80 ms `time.sleep` is **load-bearing**: without it, the hotkey's own key
release races the synthesized Ctrl, and the paste sometimes drops. If you see
"Pasted." in the log but no text appeared, that race is the suspect.

Elevated apps refuse synthetic input from a non-elevated process. The fallback
is "text is on the clipboard, the user can Ctrl+V manually" — already wired
through `notify_error` in `_do_transcribe`.

## Conventions specific to this repo

- All user-tunable knobs live in the config block at the top of `dictate.py`.
  When adding a new behavior toggle, put the constant there with a one-line
  comment, not inside a class.
- Logging: prefer `log("...")` (writes to file *and* prints) over `print`. It's
  the only reliable signal in the `pythonw` (no-console) configuration.
- Errors that the user needs to see: `notify_error()`. Routine status: `log()`
  + sound + overlay. Don't reach for `notify()` for normal events — that's why
  toasts default off.
- README.md documents user-visible config; if you add a new constant in the
  config block that a user might want to change, mirror it in the README's
  configuration table.
