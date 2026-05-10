# GPU Backend — Session Handoff

In-progress feature: add GPU acceleration on Windows by adding a
**whisper.cpp (Vulkan)** backend alongside the existing **faster-whisper
(CPU)** path, with auto-detection so the program picks GPU when
available and falls back to CPU otherwise.

This mirrors the user's Linux setup, which uses whisper.cpp built with
`-DGGML_VULKAN=1`. Vulkan is vendor-agnostic, so the same approach
works on AMD (target machine), NVIDIA, and Intel GPUs.

---

## Decisions locked in

| Question | Choice |
|---|---|
| Linux backend (parity goal) | whisper.cpp **Vulkan** |
| Windows GPU strategy | whisper.cpp **Vulkan** |
| Keep CPU path? | Yes — auto-pick. CPU stays as fallback. |
| whisper.cpp integration method | **whisper-server.exe subprocess** (HTTP, model stays warm) |
| Source of the Windows Vulkan binary | **GitHub Actions builds it on tag** (no official prebuilt exists) |
| Scope | Full feature: backend abstraction + auto-detect + tray UI, one PR |

Risk notes captured during planning:
- whisper.cpp Vulkan **Windows binaries are not in official releases**
  (only CPU / BLAS / CUDA prebuilts exist). llama.cpp ships a Vulkan win
  binary, proving the build is straightforward in CI.
- Two model storage locations now coexist: `~/.cache/huggingface/hub`
  (faster-whisper / CT2) and `%LOCALAPPDATA%\AriasSTT\models\`
  (whisper.cpp GGUF). For `medium.en` this is ~3 GB if the user keeps
  both. Document, don't dedupe.
- Output text differs slightly between backends (segmenting,
  punctuation). Users may notice if they switch mid-session.

---

## Files created (new)

```
backends/
  __init__.py                     # exports Backend, FasterWhisperBackend, WhisperCppBackend
  base.py                         # Backend ABC: load / transcribe / unload / available
  faster_whisper_backend.py       # FasterWhisperBackend (CPU). Wraps the existing path.
  whisper_cpp_backend.py          # WhisperCppBackend (GPU). Spawns whisper-server, POSTs WAV.

vendor/
  whisper-cpp/.gitkeep            # Placeholder. CI / setup.bat drops binaries here.

docs/
  GPU_BACKEND_HANDOFF.md          # This file.
```

`WhisperCppBackend` does:
- Path resolution for `whisper-server.exe` (dev: `vendor/whisper-cpp/`,
  bundled: `sys._MEIPASS/vendor/whisper-cpp/`).
- GGUF model download to `%LOCALAPPDATA%\AriasSTT\models\` from
  `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/<file>`.
  Map of model name → filename in `MODEL_FILE_MAP`.
- Spawns `whisper-server.exe` on a free localhost port, polls the HTTP
  root until ready (60 s cap), captures stderr tail on failure.
- Hand-rolled multipart POST to `/inference` (no `requests` dep).
- Encodes audio as 16-bit PCM WAV via `scipy.io.wavfile` (already a dep).

`Backend.available()` for the GPU class returns `False` if not Windows
or the binary is missing. Real Vulkan device enumeration happens inside
the binary at `load()` time; failure raises and the app falls back.

---

## Files modified

### `dictate.py` (partially done — only the config block)

Added `BACKEND = "auto"` and `BACKEND_OPTIONS = ["auto", "gpu", "cpu"]`
to the config block, right after `CPU_THREADS = 0`. **Nothing else in
`dictate.py` has been touched yet.** The wiring work below is still
pending.

### Files NOT yet modified (each has a TODO below)

- `dictate.py` — wiring, tray submenu, persistence
- `AriasSTT.spec`
- `build.bat`
- `setup.bat`
- `requirements.txt` (probably unchanged — stdlib `urllib`/`subprocess`
  are sufficient)
- `installer.iss` (probably unchanged — already does
  `dist\AriasSTT\*` recursive)
- `.github/workflows/release.yml`
- `README.md`
- `CLAUDE.md`
- `docs/ROADMAP.md`

---

## What still needs to happen

### 1. Wire `dictate.py` to use the backend abstraction

Replace the direct `WhisperModel` usage with a `Backend` instance.

- Imports (around line 157): drop the bare `from faster_whisper import
  WhisperModel`; add `from backends import Backend, FasterWhisperBackend,
  WhisperCppBackend`.
- `DictateApp.__init__` (line ~1432):
  - Replace `self.model: WhisperModel | None = None` with
    `self.backend: Backend | None = None`.
  - Read `cfg.get("backend", BACKEND)`, validate against
    `BACKEND_OPTIONS`, fall back to `BACKEND` on invalid.
  - Store as `self.current_backend`.
  - Cache `self._gpu_supported, self._gpu_unavailable_reason =
    WhisperCppBackend.available()` for tray-menu greying.
- `_save_config` (line ~1475): add `"backend": self.current_backend`.
- `load_model` (line ~1484): pick the backend class based on resolved
  choice ("auto" → GPU if `_gpu_supported`, else CPU). If the resolved
  class differs from the current `self.backend`, unload the old and
  instantiate the new. Then call `self.backend.load(target)`.
  - On auto-mode GPU load failure: log error, instantiate CPU backend,
    retry. Keep `self.current_backend = "auto"` (don't persist a
    forced-cpu — driver state may change).
- `_reload_model` (line ~1513): unchanged; it calls `load_model`.
- `_transcribe` (line ~1999): replace
  `self.model.transcribe(audio, ...)` with
  `self.backend.transcribe(audio)` (the backend handles language
  selection internally).
- `quit` (line ~2118): call `self.backend.unload()` before stopping
  the icon.
- Tooltip: include backend label, e.g.
  `f"{APP_NAME} - idle ({self.current_model} / {self.backend.label})"`.

### 2. Add `set_backend` + `_backend_submenu`

Mirror the `set_model` / `_model_submenu` pattern (line ~1494 and
line ~2020).

```python
def set_backend(self, choice: str) -> None:
    if choice not in BACKEND_OPTIONS or choice == self.current_backend:
        return
    with self._state_lock:
        if self.state != self.STATE_IDLE:
            notify_error(APP_NAME, "Finish current dictation before switching backends.")
            return
        self.state = self.STATE_BUSY
    self.current_backend = choice
    self._save_config()
    if self.icon is not None:
        try: self.icon.update_menu()
        except Exception: pass
    threading.Thread(target=self._reload_model, args=(self.current_model,), daemon=True).start()

def _backend_submenu(self) -> pystray.Menu:
    items = []
    labels = {"auto": "Auto (GPU if available)",
              "gpu":  "GPU (whisper.cpp Vulkan)",
              "cpu":  "CPU (faster-whisper)"}
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
```

Then insert `pystray.MenuItem("Backend", self._backend_submenu())` into
`_build_menu` (line ~2076), between "Model" and "Hotkey".

### 3. PyInstaller spec — bundle the vendor binaries

`AriasSTT.spec`: add to the top of the file (after the existing
`collect_all` block):

```python
import glob
from pathlib import Path
_vendor = Path(SPECPATH) / "vendor" / "whisper-cpp"
if _vendor.exists():
    for p in glob.glob(str(_vendor / "*.exe")) + glob.glob(str(_vendor / "*.dll")):
        binaries.append((p, "vendor/whisper-cpp"))
```

`build.bat`: add `--add-binary "vendor\whisper-cpp\*.exe;vendor\whisper-cpp"`
and the same for `*.dll`. (Or just delete `build.bat`'s long flag list
and have it call the spec — spec is the source of truth in CI already.)

### 4. `setup.bat` — local dev convenience

Add a `[6/6]` step that, if `vendor\whisper-cpp\whisper-server.exe`
is missing, fetches the latest CI-built artifact from the AriasSTT
repo's GitHub Releases (or skips with a notice that GPU mode will be
unavailable until the user runs it through CI once). Don't try to
install Vulkan SDK + cmake locally — too heavy.

### 5. `.github/workflows/release.yml` — build whisper.cpp Vulkan on tag

Add a job (or steps before the existing "Bundle with PyInstaller" step)
that runs on `windows-latest`:

1. `humbletim/install-vulkan-sdk@v1.2` (or jurplel/install-vulkan-sdk).
2. Check out `ggerganov/whisper.cpp` at a pinned tag (e.g. `v1.8.4`)
   into a sibling dir.
3. `cmake -S whisper.cpp -B whisper.cpp/build -DGGML_VULKAN=1
   -DWHISPER_BUILD_SERVER=ON -DCMAKE_BUILD_TYPE=Release -A x64`
4. `cmake --build whisper.cpp/build --config Release -j`
5. Copy `whisper.cpp/build/bin/Release/whisper-server.exe` and all
   accompanying `*.dll` into `vendor/whisper-cpp/`.
6. Cache the build between runs (`actions/cache@v4` keyed on the pinned
   whisper.cpp tag).

The PyInstaller step then picks them up via the spec change above.

Pin the whisper.cpp tag at the top of the workflow as a constant so
upgrades are explicit.

### 6. Docs

- `README.md`: add "Backend" row to the config table; document
  `%LOCALAPPDATA%\AriasSTT\models\` as the GGUF cache; mention the
  Vulkan requirement.
- `CLAUDE.md`: update the architecture section to describe the backend
  abstraction (`backends/` module) and the two model storage locations.
  Note that the inference object is no longer `self.model` — it's
  `self.backend`.
- `docs/ROADMAP.md`: add a v0.3.0 entry for "GPU acceleration via
  whisper.cpp Vulkan".

---

## How to verify when picking back up

There is no test harness. Verification flow per CLAUDE.md:

1. `setup.bat` (idempotent — reuses existing venv).
2. `venv\Scripts\python dictate.py` (console output).
3. Watch the log: should print `[backend:gpu]` or `[backend:cpu]`
   lines on first toggle.
4. Confirm tray "Backend" submenu shows three radio items, with GPU
   greyed when `vendor/whisper-cpp/` is empty.
5. Toggle hotkey → speak → release → text should paste. Inference time
   in the log should be noticeably lower on GPU.
6. Switch backend in the tray → next toggle should use the new one.

For the CI build path, push a `vTEST` tag to a throwaway branch and
watch `gh run list --workflow=release.yml --limit 1` until the artifact
is attached to the GitHub release.

---

## Task list state at handoff

| # | Status | Subject |
|---|---|---|
| 1 | done | Inspect build pipeline + spec + installer |
| 2 | done | Design backend abstraction module |
| 3 | done | Implement FasterWhisperBackend |
| 4 | done | Implement WhisperCppBackend |
| 5 | **in progress** | Hardware probe + auto-pick logic |
| 6 | **in progress** | Wire backends into DictateApp |
| 7 | pending | Add Backend tray submenu |
| 8 | pending | GitHub Actions: build whisper.cpp Vulkan on tag |
| 9 | pending | Update PyInstaller spec + installer.iss |
| 10 | pending | Update README + CLAUDE.md docs |

`dictate.py` still imports `from faster_whisper import WhisperModel` and
calls `self.model.transcribe(...)` directly. The backend module exists
but is not yet referenced from `dictate.py`. The only edit applied so
far is the new `BACKEND` / `BACKEND_OPTIONS` constants in the config
block.

When resuming: start at "Wire `dictate.py` to use the backend
abstraction" above. Everything else flows from that.
