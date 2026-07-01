# Plan 004: A downloaded GGUF model is rejected if it's truncated or fails a pinned digest, instead of being fed to whisper-server

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 10b48d1..HEAD -- backends/whisper_cpp_backend.py`
> If that file changed since this plan was written, compare the "Current state"
> excerpt against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 001 (adds a test to `tests/test_backends.py`)
- **Category**: security (integrity)
- **Planned at**: commit `10b48d1`, 2026-07-01

## Why this matters

The GPU backend downloads GGUF model files (~40 MB–3 GB) from HuggingFace on
first use and accepts them if the file merely exists and is non-empty. A dropped
connection (leaving a short file), a corrupted-but-non-empty `.part`, or a
substituted CDN response is accepted as a valid model and handed to
`whisper-server`, which then either crashes (unrecoverable without manually
deleting the cache) or emits garbage transcriptions with no obvious cause. This
plan adds two integrity gates: a **truncation check** (bytes written must match
the HTTP `Content-Length`) that needs no external data, and an **optional pinned
SHA256** check that becomes active once digests are filled in. Blast radius is
lower than executable-integrity (this artifact is data, not code), which is why
it's P2, but the fix is cheap and unit-testable.

## Current state

`backends/whisper_cpp_backend.py`:

```python
# line 50
MODEL_FILE_MAP: dict[str, str] = {
    "tiny.en":   "ggml-tiny.en.bin",
    "base.en":   "ggml-base.en.bin",
    "small.en":  "ggml-small.en.bin",
    "medium.en": "ggml-medium.en.bin",
    "large-v3":  "ggml-large-v3.bin",
}

# line 58
HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"

# line 176 (method on WhisperCppBackend)
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
```

- `import hashlib` is **not** currently imported in this file; the top imports are
  `http.client, io, json, os, shutil, socket, subprocess, sys, threading, time,
  urllib.error, urllib.request, uuid` plus `numpy`, `scipy.io.wavfile`, and
  `from .base import Backend, LogFn`.
- `_models_dir()` (line 114) returns the per-platform models directory and is the
  monkeypatch point the tests use.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Backend tests (no display) | `python3 -m pytest tests/test_backends.py -q` | all pass |
| Ruff | `python3 -m ruff check .` | exit 0 |

## Scope

**In scope**:
- `backends/whisper_cpp_backend.py` — add `import hashlib`, a `MODEL_SHA256` map,
  a `_sha256` helper, and rewrite `_ensure_model_file`
- `tests/test_backends.py` — add truncation + hash-mismatch tests
- `plans/README.md` — status update

**Out of scope** (do NOT touch):
- `MODEL_FILE_MAP` keys/values and `HF_BASE` — the download source is unchanged.
- The `load()` / `_wait_ready()` / `transcribe()` paths — integrity is enforced
  only at `_ensure_model_file`.
- Do NOT invent SHA256 values. Leave `MODEL_SHA256` values as `None` unless you
  can source the real digests from the official repo (see Step 2 note).

## Git workflow

- Branch: `advisor/004-model-integrity`
- One commit, conventional style: `fix(gpu): verify GGUF download length + optional sha256 before use`
- Do NOT push or open a PR unless asked.

## Steps

### Step 1: Add `import hashlib` and a `_sha256` helper

Add `import hashlib` to the stdlib import block near the top of
`backends/whisper_cpp_backend.py` (keep the existing alphabetical-ish grouping).
Then add this module-level helper near `_models_dir` (after line ~122):

```python
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
```

**Verify**: `grep -n 'def _sha256' backends/whisper_cpp_backend.py` → one match.

### Step 2: Add the (optional) pinned-digest map

Right after `MODEL_FILE_MAP` (line ~56), add:

```python
# Known SHA256 digests for the GGUF model files, keyed by filename. These are
# OPTIONAL: a value of None skips digest verification for that model and the code
# falls back to the Content-Length truncation check. Populate with the real
# digests from the official source to get full tamper/corruption detection:
#   https://huggingface.co/ggerganov/whisper.cpp/tree/main
# (each file page shows its sha256), or run `sha256sum ggml-<name>.bin` on a
# known-good local copy. Do NOT guess these values — a wrong digest rejects a
# valid model.
MODEL_SHA256: dict[str, "str | None"] = {
    "ggml-tiny.en.bin":   None,
    "ggml-base.en.bin":   None,
    "ggml-small.en.bin":  None,
    "ggml-medium.en.bin": None,
    "ggml-large-v3.bin":  None,
}
```

> If you have a verified way to obtain the real digests (e.g. the operator
> provides them or a trusted local copy exists), fill them in. Otherwise ship
> with `None` — the truncation guard in Step 3 is still a real improvement, and
> the digest check activates automatically once values are added.

**Verify**: `grep -n 'MODEL_SHA256' backends/whisper_cpp_backend.py` → shows the map.

### Step 3: Rewrite `_ensure_model_file` with the guards

Replace the body of `_ensure_model_file` (lines ~176-202) with:

```python
    def _ensure_model_file(self, model_name: str) -> Path:
        fname = MODEL_FILE_MAP.get(model_name)
        if fname is None:
            raise ValueError(f"WhisperCppBackend: unsupported model {model_name!r}")
        path = _models_dir() / fname
        expected_hash = MODEL_SHA256.get(fname)

        if path.exists() and path.stat().st_size > 0:
            if expected_hash is None or _sha256(path) == expected_hash:
                return path
            # Cached file fails its known digest -> corrupt/stale; re-download.
            self._log(f"[backend:gpu] Cached {fname} failed sha256; re-downloading.")
            try:
                path.unlink()
            except OSError:
                pass

        url = HF_BASE + fname
        self._log(f"[backend:gpu] Downloading {fname} from HuggingFace ...")
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as f:
                clen = resp.headers.get("Content-Length")
                expected_len = int(clen) if clen and clen.isdigit() else None
                written = 0
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
            # Truncation guard: a dropped connection leaves a short file.
            if expected_len is not None and written != expected_len:
                raise OSError(
                    f"download truncated: got {written} of {expected_len} bytes"
                )
            # Integrity guard: verify a pinned digest when one is known.
            if expected_hash is not None:
                actual = _sha256(tmp)
                if actual != expected_hash:
                    raise OSError(
                        f"sha256 mismatch for {fname}: {actual} != {expected_hash}"
                    )
            tmp.replace(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        self._log(f"[backend:gpu] Saved model to {path}")
        return path
```

**Verify**: `grep -n 'download truncated' backends/whisper_cpp_backend.py` → one match.

### Step 4: Add tests

Append to `tests/test_backends.py`:

```python
class _FakeResp:
    """Minimal stand-in for the urlopen response context manager."""
    def __init__(self, body: bytes, content_length):
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Length": content_length} if content_length is not None else {}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self, n=-1):
        return self._buf.read(n)


def _install_fake_urlopen(monkeypatch, body, content_length):
    def _fake(url, timeout=None):
        return _FakeResp(body, content_length)
    monkeypatch.setattr("urllib.request.urlopen", _fake)


def test_ensure_model_file_rejects_truncated_download(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    # Content-Length says 100 but the body is only 10 bytes -> truncated.
    _install_fake_urlopen(monkeypatch, body=b"0123456789", content_length="100")
    backend = WhisperCppBackend(log=lambda _m: None)
    import pytest
    with pytest.raises(OSError):
        backend._ensure_model_file("tiny.en")
    # The bad .part must be cleaned up, and no final file promoted.
    fname = MODEL_FILE_MAP["tiny.en"]
    assert not (tmp_path / fname).exists()
    assert not (tmp_path / (fname + ".part")).exists()


def test_ensure_model_file_accepts_complete_download(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    body = b"x" * 64
    _install_fake_urlopen(monkeypatch, body=body, content_length=str(len(body)))
    backend = WhisperCppBackend(log=lambda _m: None)
    result = backend._ensure_model_file("tiny.en")
    assert result.read_bytes() == body


def test_ensure_model_file_rejects_bad_digest(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    import backends.whisper_cpp_backend as wc
    fname = MODEL_FILE_MAP["tiny.en"]
    # Pin an obviously-wrong digest; a correct-length body must still be rejected.
    monkeypatch.setitem(wc.MODEL_SHA256, fname, "0" * 64)
    body = b"y" * 32
    _install_fake_urlopen(monkeypatch, body=body, content_length=str(len(body)))
    backend = WhisperCppBackend(log=lambda _m: None)
    import pytest
    with pytest.raises(OSError):
        backend._ensure_model_file("tiny.en")
    assert not (tmp_path / fname).exists()
```

> These import `pytest` locally to avoid touching the file header. `WhisperCppBackend`
> and `MODEL_FILE_MAP` are already imported at the top of `test_backends.py` by
> plan 001; add `import io` at the top if it isn't there.

**Verify**: `python3 -m pytest tests/test_backends.py -q` → all pass (including the
3 new tests and plan 001's short-circuit test, which still short-circuits because
the default `MODEL_SHA256["ggml-tiny.en.bin"]` is `None`).

### Step 5: Update the plan index

Set this plan's row in `plans/README.md` to `DONE`.

## Test plan

- New tests in `tests/test_backends.py`: truncation rejection, complete-download
  acceptance, bad-digest rejection.
- Model after the existing `test_ensure_model_file_*` tests from plan 001.
- Verification: `python3 -m pytest tests/test_backends.py -q` → all pass, no
  network hit (urlopen is mocked in every case).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'download truncated' backends/whisper_cpp_backend.py` → one match
- [ ] `grep -n 'def _sha256' backends/whisper_cpp_backend.py` → one match
- [ ] `python3 -m pytest tests/test_backends.py -q` exits 0 with the 3 new tests passing
- [ ] `python3 -m ruff check .` exits 0
- [ ] `MODEL_SHA256` values are either real verified digests or `None` — no guessed hashes
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` row for 004 says DONE

## STOP conditions

Stop and report back if:

- `_ensure_model_file` doesn't match the "Current state" excerpt (drift).
- A test needs a real network call to pass — it doesn't; the mock is complete. If
  you can't make it pass with the mock, STOP (the code likely diverged).
- You're tempted to fill `MODEL_SHA256` with values you can't verify — don't;
  leave them `None` and report that pinned digests are a follow-up needing the
  official source.

## Maintenance notes

- When whisper.cpp publishes new model revisions, a pinned digest will (correctly)
  reject the old cached file and re-download. Update `MODEL_SHA256` deliberately
  when bumping.
- The truncation guard depends on the server sending `Content-Length`; HuggingFace
  does for these static files, but if it ever chunk-encodes, the guard silently
  no-ops (still safe, just weaker) — the pinned digest is the real backstop.
- Reviewer should confirm the happy-path download is unchanged in behavior for a
  correct file (same bytes land at the same path).
