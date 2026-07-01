# Plan 001: A one-command test + lint baseline exists and runs in CI on every push

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 10b48d1..HEAD -- dictate.py backends/ .github/ requirements.txt`
> If any of those changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (this plan unblocks 002–005)
- **Category**: tests / dx
- **Planned at**: commit `10b48d1`, 2026-07-01

## Why this matters

Auritus has **no automated verification of any kind** — no tests, no linter, no
typechecker. The only CI (`.github/workflows/release.yml`) builds a Windows
installer on tag push and never executes app logic for correctness. Every change
to `dictate.py` (2833 lines, the highest-churn file in the repo) is verified only
by a human running the app, pressing the hotkey, and reading a log. This plan
adds a fast, headless test + lint job that runs on every push/PR. It is the
prerequisite that makes plans 002–005 (and any future refactor) safe to verify.

The realistic obstacle: `dictate.py` imports `sounddevice`, `pynput`, `tkinter`,
and `pystray` at module top level. On Linux those are display/audio-coupled, so a
naïve `pytest` fails at import. This plan handles that with `xvfb` + system
packages in CI, and ships a `backends/`-only fallback that needs neither.

## Current state

- `backends/whisper_cpp_backend.py` — the GPU backend; contains pure, I/O-free
  helpers that are the cleanest first test targets. Importing it pulls
  `faster_whisper` (via `backends/__init__.py`) but nothing display/audio-coupled.

  ```python
  # backends/whisper_cpp_backend.py:50
  MODEL_FILE_MAP: dict[str, str] = {
      "tiny.en":   "ggml-tiny.en.bin",
      "base.en":   "ggml-base.en.bin",
      "small.en":  "ggml-small.en.bin",
      "medium.en": "ggml-medium.en.bin",
      "large-v3":  "ggml-large-v3.bin",
  }
  # backends/whisper_cpp_backend.py:446
  def _build_multipart(wav_bytes: bytes, *, language: str) -> tuple[bytes, str]:
      """Hand-rolled multipart so we don't pull in `requests` for one POST."""
      boundary = f"----Auritus-{uuid.uuid4().hex}"
      ...
      return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
  # backends/whisper_cpp_backend.py:176 (method on WhisperCppBackend)
  def _ensure_model_file(self, model_name: str) -> Path:
      fname = MODEL_FILE_MAP.get(model_name)
      if fname is None:
          raise ValueError(f"WhisperCppBackend: unsupported model {model_name!r}")
      path = _models_dir() / fname
      if path.exists() and path.stat().st_size > 0:   # short-circuit: no download
          return path
      url = HF_BASE + fname
      ...
  ```

- `dictate.py` — the app. Pure, side-effect-free helpers worth characterizing
  (all defined at module scope, all reachable once the module imports):

  ```python
  # dictate.py:276
  def _parse_version(s: str) -> tuple[int, ...]:
      """'v0.2.1' -> (0, 2, 1); stops at first non-numeric piece."""
  # dictate.py:348
  def is_valid_hotkey(spec: str) -> bool:
      try:
          keyboard.HotKey.parse(spec)   # NB: needs pynput importable
          return True
      except Exception:
          return False
  # dictate.py:1576
  def clean_text(text: str) -> str:
      text = _TIMESTAMP_RE.sub(" ", text)
      ...
      return text.strip()
  ```

- `dictate.py` module-top imports that block a naïve import on headless Linux:

  ```python
  # dictate.py:185
  import numpy as np
  import sounddevice as sd          # dlopens libportaudio at import
  from scipy.io import wavfile
  import pyperclip
  from pynput import keyboard       # connects to X on Linux at import
  from PIL import Image, ImageDraw
  import pystray
  import tkinter as tk              # needs python3-tk package installed
  ```
  Note `dictate.py` has **no** `from __future__ import annotations`, and methods
  use annotations like `-> pystray.Menu`, so `pystray` must be genuinely
  importable (not stubbed) for the module to import. This is why the plan uses
  real packages under `xvfb` rather than `sys.modules` stubs.

- `requirements.txt` (unpinned): `faster-whisper pynput pyperclip sounddevice numpy scipy pystray Pillow plyer`.

- `.github/workflows/release.yml` — the only workflow; `on: push: tags: ['v*']`.
  Do **not** modify it (it is the release pipeline). Add a **new** workflow file.

- Repo conventions: conventional-commit messages (`git log` shows `fix:`,
  `feat(linux):`). No existing `pyproject.toml`, `tests/`, or `conftest.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Python present | `python3 --version` | 3.10+ |
| Install test deps (local) | `python3 -m pip install pytest ruff` | exit 0 |
| Run tests (backends-only, no display needed) | `python3 -m pytest tests/test_backends.py -q` | all pass |
| Run all tests (needs display or xvfb) | `xvfb-run -a python3 -m pytest -q` (Linux) | all pass |
| Lint | `python3 -m ruff check .` | exit 0 (or only pre-existing warnings, see Step 4) |

## Scope

**In scope** (create/modify only these):
- `pyproject.toml` (create — ruff + pytest config only; do not add build metadata)
- `tests/__init__.py` (create, empty)
- `tests/conftest.py` (create)
- `tests/test_backends.py` (create)
- `tests/test_dictate_helpers.py` (create)
- `.github/workflows/ci.yml` (create)
- `plans/README.md` (status update only)

**Out of scope** (do NOT touch):
- `dictate.py` and everything in `backends/` — this plan only *reads* them. Any
  behavior change belongs to plans 002–005.
- `.github/workflows/release.yml` — the release pipeline; leave it exactly as is.
- `requirements.txt` — pinning is a separate finding (not in this bundle).

## Git workflow

- Branch: `advisor/001-verification-baseline`
- One commit is fine; conventional-commit style, e.g.
  `test: add pytest + ruff baseline and CI job`
- Do NOT push or open a PR unless the operator asks.

## Steps

### Step 1: Add `pyproject.toml` with ruff + pytest config

Create `pyproject.toml` at the repo root:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py310"
line-length = 100
# Vendored / generated code is not ours to lint.
extend-exclude = ["vendor", "third_party", "build", "dist", "venv", "installer-output"]

[tool.ruff.lint]
# Start conservative: pyflakes (F) + a subset of pycodestyle (E). Expand later.
select = ["F", "E9"]
```

**Verify**: `python3 -m pip install ruff && python3 -m ruff check . ` → exits 0
or prints only findings (Step 4 decides what to do with them).

### Step 2: Add the `backends/` tests (the no-display floor)

Create `tests/__init__.py` (empty) and `tests/test_backends.py`:

```python
"""Unit tests for the pure, I/O-free parts of the inference backends.
These need only numpy/scipy/faster-whisper on the path — no display, no audio,
no GTK — so they run on a bare CI runner."""
import io
import numpy as np
from scipy.io import wavfile

from backends.whisper_cpp_backend import (
    MODEL_FILE_MAP,
    WhisperCppBackend,
    _build_multipart,
    _models_dir,
)

# Mirror of dictate.MODEL_OPTIONS (kept here to avoid importing the GUI module).
# If dictate.py adds a model, this list and MODEL_FILE_MAP must both grow.
EXPECTED_MODELS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]


def test_model_file_map_covers_every_option():
    assert set(MODEL_FILE_MAP) == set(EXPECTED_MODELS)
    for fname in MODEL_FILE_MAP.values():
        assert fname.startswith("ggml-") and fname.endswith(".bin")


def test_build_multipart_shape():
    wav = b"RIFFfake"
    body, content_type = _build_multipart(wav, language="en")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    assert boundary.encode() in body
    assert wav in body
    assert b'name="file"' in body
    assert b'name="language"' in body
    # closing boundary present
    assert body.rstrip().endswith(b"--" + boundary.encode() + b"--")


def test_ensure_model_file_short_circuits_on_existing_file(tmp_path, monkeypatch):
    # Point the models dir at a temp dir and pre-create a non-empty model file;
    # _ensure_model_file must return it WITHOUT attempting a download.
    monkeypatch.setattr(
        "backends.whisper_cpp_backend._models_dir", lambda: tmp_path
    )
    fname = MODEL_FILE_MAP["tiny.en"]
    (tmp_path / fname).write_bytes(b"not empty")

    def _boom(*a, **k):
        raise AssertionError("network was hit despite a cached model file")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    backend = WhisperCppBackend(log=lambda _m: None)
    result = backend._ensure_model_file("tiny.en")
    assert result == tmp_path / fname


def test_ensure_model_file_rejects_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backends.whisper_cpp_backend._models_dir", lambda: tmp_path
    )
    backend = WhisperCppBackend(log=lambda _m: None)
    try:
        backend._ensure_model_file("does-not-exist")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown model")
```

**Verify**: `python3 -m pip install -r requirements.txt pytest` then
`python3 -m pytest tests/test_backends.py -q` → all pass (5 tests). If installing
the full `requirements.txt` is slow, the minimum for this file is
`pip install numpy scipy faster-whisper`.

### Step 3: Add the `dictate.py` helper tests (needs a display or xvfb)

Create `tests/conftest.py` — it makes `import dictate` importable in tests and
keeps its import side effects (it creates `~/.local/share/Auritus/`) out of the
real home dir:

```python
import os
import pathlib
import pytest

# dictate.py creates its data dir at import time (LOG_PATH.parent.mkdir(...)).
# Redirect it to a temp location so importing the module in CI doesn't touch
# the real user profile. NOTE: this only isolates POSIX (dictate.py reads
# XDG_DATA_HOME on Linux/macOS but %LOCALAPPDATA% on Windows). CI runs ubuntu, so
# this is sufficient; running the suite locally on Windows will still create the
# real %LOCALAPPDATA%\Auritus\ dir on import.
os.environ.setdefault("XDG_DATA_HOME", str(pathlib.Path(__file__).parent / "_tmp_data"))


@pytest.fixture(scope="session")
def dictate():
    """Import dictate once per session. Skips the whole module if the GUI/audio
    imports can't load (e.g. no display and no xvfb), so the backends tests
    still run and the suite stays green as a partial baseline."""
    try:
        import dictate as _d
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"dictate.py not importable in this environment: {exc}")
    return _d
```

Create `tests/test_dictate_helpers.py`:

```python
"""Characterization tests for the pure helpers in dictate.py. These lock in
current behavior so future edits to the 2833-line module can't silently change
version parsing, hotkey validation, or transcript cleanup."""
import pytest


def test_parse_version_basic(dictate):
    assert dictate._parse_version("v0.2.1") == (0, 2, 1)
    assert dictate._parse_version("0.3.3") == (0, 3, 3)


def test_parse_version_stops_at_non_numeric(dictate):
    # Documented behavior: '1.0.0-rc1' -> (1, 0, 0) is WRONG per the docstring;
    # it stops at the first non-numeric PIECE, so '1.0.0-rc1' -> (1, 0) ... but
    # '1.0.0' has no such piece. Assert the real current behavior, whatever it is,
    # by pinning the two documented examples from the docstring:
    assert dictate._parse_version("1.0.0-rc1") == (1, 0)
    assert dictate._parse_version("") == (0,)


def test_parse_version_ordering(dictate):
    assert dictate._parse_version("0.3.4") > dictate._parse_version("0.3.3")
    assert dictate._parse_version("v0.10.0") > dictate._parse_version("v0.9.9")


@pytest.mark.parametrize("spec", [
    "<ctrl>+<alt>+<space>", "<f9>", "<ctrl>+<shift>+d",
])
def test_is_valid_hotkey_accepts_known_good(dictate, spec):
    assert dictate.is_valid_hotkey(spec) is True


@pytest.mark.parametrize("spec", ["", "not a hotkey", "<ctrl>+"])
def test_is_valid_hotkey_rejects_garbage(dictate, spec):
    assert dictate.is_valid_hotkey(spec) is False


def test_clean_text_strips_timestamps_and_collapses_space(dictate):
    assert dictate.clean_text("  hello   world  ") == "hello world"
    assert dictate.clean_text("<|0.00|>hi there") == "hi there"


def test_clean_text_empty(dictate):
    assert dictate.clean_text("") == ""
```

> If `_parse_version("1.0.0-rc1")` does not equal `(1, 0)` when you run it, do
> NOT change `dictate.py` — update the assertion to the real returned value and
> note it in your report. These are characterization tests: they record current
> behavior, they don't dictate it.

**Verify (Linux)**: `xvfb-run -a python3 -m pytest -q` → all pass.
**Verify (with a real display / macOS / Windows)**: `python3 -m pytest -q` → all pass.
If `dictate` can't import even under xvfb, the `dictate` fixture skips these and
`test_backends.py` still passes — see STOP conditions.

### Step 4: Triage the first `ruff check` output

Run `python3 -m ruff check .`. Because `select = ["F", "E9"]` is conservative,
this should surface only real problems (unused imports, undefined names, syntax
errors), not style noise.

- If it reports **0 findings**: done, move on.
- If it reports findings **in `dictate.py`/`backends/`**: do NOT fix them here
  (out of scope). Instead add the specific rule/line to a `# noqa` **only if**
  it's a false positive, or record the finding in your report for a follow-up.
  The goal of this plan is that `ruff check .` **exits 0 on the code as it is
  today** — if a real pre-existing issue blocks that, narrow the `select` set or
  add a targeted `per-file-ignores` entry in `pyproject.toml` and note it.

**Verify**: `python3 -m ruff check .` → exit 0.

### Step 5: Add the CI workflow

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: ['**']
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: requirements.txt
      - name: System libs for headless import of dictate.py
        run: sudo apt-get update && sudo apt-get install -y xvfb python3-tk libportaudio2
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt
          python -m pip install pytest ruff
      - name: Lint
        run: python -m ruff check .
      - name: Test
        run: xvfb-run -a python -m pytest -q
```

**Verify**: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
→ prints `yaml ok`. (Real CI verification happens when the branch is pushed —
out of scope for local execution.)

### Step 6: Update the plan index

Set this plan's row in `plans/README.md` to `DONE`.

## Test plan

- New files: `tests/test_backends.py` (5 tests — no display needed) and
  `tests/test_dictate_helpers.py` (version parsing, hotkey validation, text
  cleanup — needs display/xvfb).
- No existing test to model after (this is the first suite); follow the shapes
  above.
- Verification: `python3 -m pytest tests/test_backends.py -q` passes with no
  display; `xvfb-run -a python3 -m pytest -q` passes the full suite.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python3 -m pytest tests/test_backends.py -q` exits 0 with ≥5 passing tests
- [ ] `xvfb-run -a python3 -m pytest -q` exits 0 (Linux) — OR, if `dictate` is
      unimportable even under xvfb, `test_dictate_helpers.py` is *skipped* (not
      failed) and you have recorded the import blocker in your report
- [ ] `python3 -m ruff check .` exits 0
- [ ] `.github/workflows/ci.yml` exists and is valid YAML; `release.yml` is unchanged
      (`git diff 10b48d1 -- .github/workflows/release.yml` is empty)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` row for 001 says DONE

## STOP conditions

Stop and report back (do not improvise) if:

- `import dictate` fails even under `xvfb-run` after installing `python3-tk`,
  `libportaudio2`, and the full `requirements.txt`. In that case ship Steps 1, 2,
  4, 5 (backends tests + ruff + CI, with the CI `Test` step changed to
  `xvfb-run -a python -m pytest tests/test_backends.py -q`) and report that the
  `dictate.py` helper tests need the `helpers.py` extraction (a separate,
  larger refactor) before they can run. A backends-only baseline is still a win.
- A characterization assertion fails because the real current behavior differs
  from what this plan guessed — update the assertion to reality, don't touch
  `dictate.py`.
- `ruff check .` cannot be made to exit 0 without editing `dictate.py`/`backends/`
  — narrow the rule set / add `per-file-ignores` and report the real issues found.

## Maintenance notes

- When `dictate.MODEL_OPTIONS` or `MODEL_FILE_MAP` changes, `EXPECTED_MODELS` in
  `tests/test_backends.py` must change too — `test_model_file_map_covers_every_option`
  is the guard that catches a model added to one but not the other.
- The `select = ["F", "E9"]` ruff set is deliberately minimal so this lands
  green. Widening it (add `E`, `I`, `UP`) is a good follow-up once the code is
  clean.
- Plans 002–005 add one test each to `tests/`; they assume this harness exists.
- Follow-up worth filing: extract the pure helpers (`_parse_version`,
  `is_valid_hotkey`, `_key_to_vk`, `_spec_to_winhotkey`, `clean_text`,
  `_make_wav_tone`, `_round_rect_points`, `_HoldChord`) into a GUI-free
  `helpers.py` so the helper tests need no display at all (this is audit finding
  TEST-03 option b, and dovetails with the platform-shim extraction, tech-debt
  finding TECH-01).
