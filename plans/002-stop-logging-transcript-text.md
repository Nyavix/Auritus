# Plan 002: Transcribed speech is no longer written verbatim to the persistent log by default

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 10b48d1..HEAD -- dictate.py`
> If `dictate.py` changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 001 (uses the `tests/` harness + `dictate` fixture it creates)
- **Category**: security (data minimization / privacy)
- **Planned at**: commit `10b48d1`, 2026-07-01

## Why this matters

Auritus dictation is arbitrary user speech — passwords, 2FA codes, medical and
financial details, private messages. Today the full transcript is written
verbatim into a long-lived, unrotated log file:

- Linux: `~/.local/share/Auritus/auritus.log`
- Windows: `%LOCALAPPDATA%\Auritus\auritus.log`

The file is created with the process umask (0644 → group/other-readable on
Linux) and never truncated, so every dictation accumulates in plaintext at rest.
This is a persistent disclosure of exactly the sensitive content the app exists
to capture, and it directly contradicts the product's "all user data stays
local / private" positioning (see `docs/PRD.md`). The fix is small: stop logging
the transcript body by default, keep only a length, and gate the full text
behind an explicit opt-in debug flag.

## Current state

- `dictate.py:216` — the logger writes to the persistent file and stdout:

  ```python
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
  ```

- `dictate.py:2463` — the offending line, inside `_do_transcribe`, logs the whole
  transcript:

  ```python
          log(f"Transcribed: {text!r}")
  ```

- For contrast, the cancel path already logs only a length (this is the pattern
  to follow):

  ```python
  # dictate.py:2455
              log(f"Transcription cancelled; dropping {len(text)} chars.")
  ```

- The config block at the top of the file is the repo's convention for
  user-tunable flags. Nearby existing flags for reference:

  ```python
  # dictate.py:68
  # Show toast notifications for routine events. Off by default on Windows ...
  SHOW_NOTIFICATIONS = not IS_WINDOWS

  # Play a short sound when recording starts and stops.
  PLAY_SOUNDS = True
  ```

- `_DATA_DIR` / `LOG_PATH` are defined at `dictate.py:205-213`:

  ```python
  APP_NAME = "Auritus"
  ...
  LOG_PATH = _DATA_DIR / "auritus.log"
  LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
  ```

- Repo conventions (from `CLAUDE.md`): "All user-tunable knobs live in the config
  block at the top of `dictate.py`. When adding a new behavior toggle, put the
  constant there with a one-line comment." And: "if you add a new constant in the
  config block that a user might want to change, mirror it in the README's
  configuration table."

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests (needs display) | `xvfb-run -a python3 -m pytest -q` (Linux) | all pass |
| Confirm redaction | `grep -n 'Transcribed {len(text)} chars' dictate.py` | one match (the redacted default path) |
| Confirm gate | `grep -n 'if DEBUG_LOG_TEXT:' dictate.py` | one match (raw log now behind the flag) |
| Ruff | `python3 -m ruff check .` | exit 0 |

## Scope

**In scope**:
- `dictate.py` — the config block (add one constant) and the single log line at ~2463
- `README.md` — add a row for the new config constant (mirror convention)
- `tests/test_dictate_helpers.py` — add one test (created by plan 001)
- `plans/README.md` — status update

**Out of scope** (do NOT touch):
- The `log()` function itself — it stays a generic logger; the redaction is at
  the call site, not in `log()`.
- Any other `log(...)` call. Only the transcript-body line changes. (Do NOT go
  hunting for other "sensitive" logs in this plan — if you spot one, note it in
  your report.)
- Log rotation / size capping — a real improvement but a separate finding; not
  in scope here.

## Git workflow

- Branch: `advisor/002-redact-transcript-log`
- One commit, conventional style: `fix(privacy): don't log transcript text by default`
- Do NOT push or open a PR unless asked.

## Steps

### Step 1: Add an opt-in debug constant to the config block

In the config block near `SHOW_NOTIFICATIONS`/`PLAY_SOUNDS` (around `dictate.py:68-74`),
add:

```python
# Write the full transcribed text into auritus.log. OFF by default: dictation
# can contain passwords, 2FA codes, and other secrets, and the log is a
# long-lived plaintext file. Turn on only for local debugging of bad output.
DEBUG_LOG_TEXT = False
```

**Verify**: `grep -n 'DEBUG_LOG_TEXT' dictate.py` → shows the new constant.

### Step 2: Redact the transcript log line

Replace the line at `dictate.py:2463`:

```python
            log(f"Transcribed: {text!r}")
```

with:

```python
            if DEBUG_LOG_TEXT:
                log(f"Transcribed: {text!r}")
            else:
                log(f"Transcribed {len(text)} chars.")
```

**Verify**: `grep -n 'Transcribed' dictate.py` shows the gated block; the default
path logs only a count.

### Step 3 (optional hardening, keep if trivial): tighten log file permissions on creation

Immediately after `LOG_PATH.parent.mkdir(...)` at `dictate.py:213`, the log file
is created lazily by `log()`. Add a best-effort chmod so the file is user-only on
POSIX. Insert right after the `mkdir` line:

```python
# Best-effort: keep the log user-readable only (it may contain diagnostic text).
if not IS_WINDOWS:
    try:
        LOG_PATH.touch(exist_ok=True)
        os.chmod(LOG_PATH, 0o600)
    except Exception:
        pass
```

> `os` is already imported at `dictate.py:147`. If this touch/chmod causes any
> import-time error in the test suite, remove Step 3 (it is optional) and keep
> Steps 1–2, which are the core fix. Report that you dropped Step 3.

**Verify**: `xvfb-run -a python3 -m pytest -q` still passes (import side effect is
harmless).

### Step 4: Add a regression test

In `tests/test_dictate_helpers.py` (created by plan 001), add:

```python
def test_transcript_not_logged_by_default(dictate, monkeypatch, tmp_path):
    # With DEBUG_LOG_TEXT off (the default), the transcript body must never
    # reach the log. We capture what log() writes and assert the secret text
    # is absent while a length line is present.
    assert dictate.DEBUG_LOG_TEXT is False
    written = []
    monkeypatch.setattr(dictate, "log", lambda msg: written.append(msg))
    secret = "my password is hunter2"
    # Reproduce the exact default-path branch from _do_transcribe:
    if dictate.DEBUG_LOG_TEXT:
        dictate.log(f"Transcribed: {secret!r}")
    else:
        dictate.log(f"Transcribed {len(secret)} chars.")
    joined = "\n".join(written)
    assert secret not in joined
    assert "chars." in joined
```

> This test pins the contract at the branch level. It does not exercise the full
> `_do_transcribe` (that needs a backend + audio); the point is to guarantee the
> default branch cannot emit the transcript body. If you can cheaply drive
> `_do_transcribe` with a fake backend instead, that's better — but do not spend
> more than a few minutes; the branch-level test is sufficient.

**Verify**: `xvfb-run -a python3 -m pytest -q tests/test_dictate_helpers.py` → the
new test passes.

### Step 5: Mirror the constant in the README config table

In `README.md`'s configuration table (the `| \`NAME\` | default | desc |` table
around lines 97–122), add a row:

```
| `DEBUG_LOG_TEXT` | `False` | Write the full transcript into `auritus.log`. Off by default — dictation can contain secrets. Turn on only to debug bad output. |
```

**Verify**: `grep -n 'DEBUG_LOG_TEXT' README.md` → shows the new row.

### Step 6: Update the plan index

Set this plan's row in `plans/README.md` to `DONE`.

## Test plan

- New test: `test_transcript_not_logged_by_default` in `tests/test_dictate_helpers.py`
  — asserts the default branch logs a length, not the text.
- Model after the other tests in that file (created by plan 001).
- Verification: `xvfb-run -a python3 -m pytest -q` → all pass including the new test.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] The raw transcript log is now **gated**, not unconditional:
      `grep -n 'if DEBUG_LOG_TEXT:' dictate.py` → one match, and
      `grep -n 'Transcribed {len(text)} chars' dictate.py` → one match.
      (Do NOT expect zero matches for `Transcribed: {text!r}` — that call still
      exists, correctly, inside the `if DEBUG_LOG_TEXT:` branch.)
- [ ] `grep -n 'DEBUG_LOG_TEXT' dictate.py README.md` shows the constant in both
- [ ] `xvfb-run -a python3 -m pytest -q` exits 0, new test present and passing
- [ ] `python3 -m ruff check .` exits 0
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` row for 002 says DONE

## STOP conditions

Stop and report back if:

- The line at `dictate.py:2463` is not `log(f"Transcribed: {text!r}")` (drift) —
  find where the transcript is logged, or STOP if it's already been changed.
- Plan 001 has not landed and `tests/` / the `dictate` fixture don't exist — do
  001 first, or (if instructed to proceed) create a minimal `tests/conftest.py`
  with the `dictate` fixture from plan 001 Step 3 before adding the test.
- Adding Step 3's chmod breaks module import in the test suite — drop Step 3.

## Maintenance notes

- If log rotation / a size cap is added later, keep the default-off redaction —
  rotation limits volume, not sensitivity.
- Reviewer should confirm no *other* `log()` call added in the same PR reintroduces
  transcript text (e.g. a debug line during development).
- A stricter future option: redact even under `DEBUG_LOG_TEXT` after N characters,
  or hash the text. Out of scope now.
