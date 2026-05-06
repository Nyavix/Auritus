# AriasSTT

Push-to-talk Whisper dictation tray app for Windows. Press a global hotkey to
start recording, press it again to stop — the audio is transcribed locally on
the CPU with [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
copied to the clipboard, and pasted into whatever window has focus.

Built for systems without a CUDA GPU (e.g. AMD Radeon). Inference runs on the
CPU using `int8` quantization.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer on `PATH`
- A working microphone
- ~2 GB free disk for the `medium.en` model
- Internet connection for the first run (model download only)

## Install

```cmd
setup.bat
```

This will:

1. Create a virtual environment in `.\venv`
2. Install: `faster-whisper`, `pynput`, `pyperclip`, `sounddevice`, `numpy`,
   `scipy`, `pystray`, `Pillow`, `plyer`
3. Download the `medium.en` model (~1.5 GB, cached under
   `%USERPROFILE%\.cache\huggingface`)
4. Run a smoke test

## Run

Background mode (no console window — recommended):

```cmd
venv\Scripts\pythonw dictate.py
```

Foreground mode with console output (handy when debugging):

```cmd
venv\Scripts\python dictate.py
```

A blue dot appears in the system tray when AriasSTT is idle.

## Use

1. Focus any text field (Notepad, browser, IDE, Slack, anything).
2. Press **Ctrl+Alt+Space** — the tray icon turns red and a "Recording..."
   toast appears.
3. Speak.
4. Press **Ctrl+Alt+Space** again — the icon turns amber while transcribing,
   then the text is pasted into the focused window. The icon returns to blue.

If the focused app blocks synthetic keystrokes, the text is still on your
clipboard — just press Ctrl+V manually.

## Auto-start on login

```cmd
install_startup.bat
```

This drops a shortcut into your user Startup folder
(`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AriasSTT.lnk`) that
launches `pythonw dictate.py` so there is no console window.

To disable:

```cmd
uninstall_startup.bat
```

> The Startup folder is used instead of Task Scheduler because tray apps need
> the user's interactive desktop session, which the Startup folder gives you
> automatically.

## Quit cleanly

Right-click the tray icon → **Quit**. This stops the hotkey listener, closes
the audio stream, and exits the process.

## Configuration

All knobs live at the top of `dictate.py`:

| Variable | Default | Notes |
|---|---|---|
| `HOTKEY` | `"<ctrl>+<alt>+<space>"` | Initial hotkey (overridable from the tray menu — see "Changing the hotkey"). [pynput GlobalHotKeys syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys). Examples: `"<f9>"`, `"<ctrl>+<shift>+d"` |
| `HOTKEY_PRESETS` | tuples of `(spec, warning)` — see source | Choices shown in the tray "Hotkey" submenu. Combos with a non-`None` warning render with a ⚠ marker (e.g. `Ctrl+Shift+M ⚠ Teams/Outlook mute`). |
| `MODEL_SIZE` | `"medium.en"` | `tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v3` |
| `COMPUTE_TYPE` | `"int8"` | `int8` is fastest on CPU; try `int8_float32` if accuracy suffers |
| `MIC_DEVICE` | `None` | `None` = default; or an int index / name substring. List devices with `python -m sounddevice` |
| `SAMPLE_RATE` | `16000` | Whisper expects 16 kHz |
| `MAX_RECORD_SECONDS` | `300` | Hard cap on a single take |
| `AUTO_PASTE` | `True` | Set `False` to only copy to clipboard |
| `SHOW_NOTIFICATIONS` | `False` | Routine Windows toasts. Errors always toast regardless. |
| `PLAY_SOUNDS` | `True` | Short start/stop tone played via `winsound`. |
| `SOUND_START` / `SOUND_STOP` | `None` | Optional path to a custom `.wav`. `None` uses the built-in synthesized tones. |
| `SOUND_VOLUME` | `0.35` | Volume of the built-in tones (0.0–1.0). |
| `MODEL_OPTIONS` | `["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]` | Choices shown in the tray "Model" submenu. |
| `CPU_THREADS` | `0` | `0` = let faster-whisper pick. Bumping this can help on machines with lots of cores. |

After editing, just restart the app. Model and hotkey are exceptions — both
are editable from the tray menu and persisted to
`%LOCALAPPDATA%\AriasSTT\config.json` across restarts.

### Switching models on the fly

Right-click the tray icon → **Model** → pick one. The new model loads on a
background thread (you'll hear the start tone again when it's ready). Your
choice is remembered next launch.

Speed vs. accuracy on CPU, ballpark:

| Model | Relative speed | Notes |
|---|---|---|
| `tiny.en`   | ~10× faster than `medium.en` | snappy, occasional misses |
| `base.en`   | ~5× faster | good for casual dictation |
| `small.en`  | ~2× faster | solid balance |
| `medium.en` | baseline (~1× realtime) | accurate, the default |
| `large-v3`  | slower than realtime | most accurate, multilingual |

If `medium.en` feels sluggish, try `small.en` first — for short dictation
snippets the accuracy gap is usually unnoticeable.

### Custom start/stop sounds

Drop two `.wav` files anywhere and point at them:

```python
SOUND_START = r"C:\Users\you\Sounds\ding.wav"
SOUND_STOP  = r"C:\Users\you\Sounds\dong.wav"
```

To silence sounds entirely, set `PLAY_SOUNDS = False`.

### Changing the hotkey

Right-click the tray icon → **Hotkey** → pick a preset, or choose
**Custom...** to type a [pynput-syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys)
combo. The change takes effect immediately and is saved to `config.json`.

Modifiers go in angle brackets, plain letters do not:

```
<ctrl>+<shift>+d   Ctrl+Shift+D
<f9>               F9
<alt>+`            Alt+Backtick
```

To change the available presets, edit `HOTKEY_PRESETS` at the top of
`dictate.py`. The `HOTKEY` constant is only the initial value used the very
first time you launch (before `config.json` exists).

### Picking a specific microphone

```cmd
venv\Scripts\python -m sounddevice
```

Find the row for your mic and either copy its index or a unique substring of
its name into `MIC_DEVICE`:

```python
MIC_DEVICE = 3
MIC_DEVICE = "Microphone (Realtek"
```

## Troubleshooting

**Logs:** `%LOCALAPPDATA%\AriasSTT\ariasstt.log` (also reachable from the
tray menu → "Open log folder").

**No tray icon appears.** Check the log. Most likely the model failed to
load or another instance is already running.

**"No input device found."** Plug in / enable a mic, then restart the app.
You can also try setting `MIC_DEVICE` explicitly.

**Hotkey does nothing.** Another app may have grabbed it (Discord push-to-talk,
NVIDIA Overlay, Steam, etc.). Pick a different `HOTKEY`.

**Transcription is slow.** `medium.en` on CPU is ~1× realtime depending on
your CPU. Drop to `small.en` or `base.en` for snappier turnaround.

**Paste does nothing but text is on the clipboard.** Some elevated apps
(running as Administrator) refuse synthetic input from a non-elevated process.
Either run AriasSTT elevated as well, or paste with Ctrl+V yourself.

## Files

- `setup.bat` — one-shot installer (venv, deps, model)
- `dictate.py` — the tray app
- `install_startup.bat` / `uninstall_startup.bat` — login auto-start
- `README.md` — this file
