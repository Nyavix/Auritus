# Hotkey Reliability + UX Plan

Living design doc capturing why the global hotkey is unreliable in some Windows
apps, and the prioritized changes to fix it. Written after a joint research
pass with Gemini (whole-codebase + ecosystem context) and Codex (root-cause
challenge + plan critique).

Status legend: `[ ]` planned, `[~]` in progress, `[x]` shipped.

---

## Problem statement

The previous default hotkey `Ctrl+Shift+M` did not fire when Microsoft Teams,
Outlook, Discord, or some other foreground apps were active. The rebind logic
itself works — the hotkey listener simply never received the keystrokes.

## Root cause

`pynput.keyboard.GlobalHotKeys` installs a low-level keyboard hook (Windows
`WH_KEYBOARD_LL`). Hooks are dispatched in **LIFO** order: the most recently
installed hook runs first, and any hook that returns a non-zero result
**suppresses delivery** for everything downstream.

- `Ctrl+Shift+M` is the global mute toggle in Microsoft Teams, the
  mark-as-read shortcut in Outlook, and (configurable) push-to-mute in
  Discord. These apps install their own LL hooks and consume the chord.
- `LowLevelHooksTimeout` (default ~300 ms) silently drops slow hooks, so a
  CPU-busy moment can also drop a press.
- DirectInput / Raw Input apps (some games, OBS scenes) bypass LL hooks
  entirely.

What is **not** the cause: the OS-level `RegisterHotKey` API. It posts
`WM_HOTKEY` to a registered window — it does not participate in the LL hook
chain and cannot suppress hook delivery. (Codex flagged this; an earlier
hypothesis from Gemini overstated `RegisterHotKey`'s role.)

## Constraints / non-goals

- Stay single-file (`dictate.py`) until the design clearly demands a split.
- No admin-elevation requirement.
- No new heavy dependencies. `pywin32` only if a P3+ feature actually needs it
  (a `ctypes` stub usually suffices for the small Win32 surface in play).
- No automated tests are practical — this is a single-user tray app. Manual
  smoke testing only.

---

## Prioritized changes

### P0 — Drop bad defaults  `[x]` (S, ~10 LOC, `dictate.py` + `README.md`)

- Switch initial `HOTKEY` to `<ctrl>+<alt>+<space>` (uncontested, easy chord).
- Reorder `HOTKEY_PRESETS` so safe combos lead.
- Tag risky presets with a ⚠ marker in the submenu label, e.g.
  `"<ctrl>+<shift>+m  ⚠ Teams/Outlook"`.

#### Recommended preset list (ranked by safety)

| Rank | Combo | Notes |
|---|---|---|
| 1 | `<ctrl>+<alt>+<space>` | Uncommon, easy reach. Recommended default. |
| 2 | `<f9>` | Free in productivity apps, sometimes used by IDEs. |
| 3 | `<f12>` | Browser DevTools — fine outside browsers. |
| 4 | `<ctrl>+<alt>+<shift>+d` | Triple-modifier, near-zero conflict. |
| 5 | `<pause>` | Legacy key, almost never bound. |
| 6 | `<scroll_lock>` | Classic VOIP PTT key (Ventrilo / TeamSpeak heritage). |
| 7 | `<ctrl>+<shift>+m` | Conflicts with Teams/Outlook/Discord — keep but warn. |

F13–F24 are perfect on macro keyboards but absent on most laptops, so they
stay documented but out of the default preset list.

### P1 — Live key-capture dialog  `[x]` (M, ~80–100 LOC, `dictate.py`)

Replace `simpledialog.askstring` with a custom `tk.Toplevel`:

- Modal (`grab_set`), top-most, focused.
- Bind `<KeyPress>` and `<KeyRelease>`.
- Track modifier state from `event.state` bitmask + `event.keysym`.
- Live preview label updates on every keypress (`Ctrl + Shift + …`).
- Reject modifier-only chords, plain Enter, plain Escape (Escape = cancel).
- Confirm with **OK** button (or Enter on the button) — do **not** auto-confirm
  on first non-modifier keydown; users need a chance to correct.
- Convert captured keys to pynput syntax (`<ctrl>+<shift>+m` form) via a small
  `keysym → pynput-name` lookup table.
- Keep the existing typed-syntax path as an "Advanced…" link for power users.

### P2 — Push-to-talk hold mode  `[ ]` (M, ~60 LOC, `dictate.py`)

Optional dual-mode trigger. Toggle remains the default.

- New persisted config key `mode: "toggle" | "hold"`.
- Tray submenu **Mode → Toggle / Hold (PTT)**.
- Hold mode uses `pynput.keyboard.Listener` with `on_press` + `on_release`
  (not `GlobalHotKeys`, which only fires on chord completion).
- Debounce key-repeat: only act on the first transition into / out of the
  bound chord.
- Reuse the existing `MAX_RECORD_SECONDS` ceiling as a dead-man's switch
  against stuck-hot recording.
- Ignore key-down during `STATE_BUSY`; clear pending hold-state on `busy`
  exit so a release that arrived during transcription doesn't double-trigger.

### P3 — Conflict probe via RegisterHotKey  `[x]` (M, ~50 LOC, `dictate.py`)

At `set_hotkey()` time, run a Win32 `RegisterHotKey` probe:

- Create a hidden message-only window via `ctypes.windll.user32`.
- Translate the pynput chord to `MOD_CTRL/SHIFT/ALT/WIN` flags + a `VK_*` code.
- `RegisterHotKey` → check failure → immediately `UnregisterHotKey`.
- On failure: toast `"Already registered by another app — combo may be
  unreliable"`. Do not block — the user may still want it.

**Caveat:** detects only the OS-registered class of conflicts. Hook-swallow
conflicts (Teams, Discord, Outlook) won't show up here. P4 is the only
reliable detector for those.

### P4 — Empirical "Test hotkey" check  `[x]` (S, ~30 LOC, `dictate.py`)

Tray menu **"Test hotkey…"** entry:

- Arms a one-shot `pynput` listener for ~5 s.
- Prompts the user to press the bound combo (modal toast or overlay).
- Reports `✓ Detected (NN ms)` or `✗ Not received — likely swallowed by
  another app`.

This is the only way to detect hook-swallow conflicts from inside the app.

### P5 — Listener-failure resilience  `[x]` (S, ~10 LOC, `dictate.py`)

If `_start_hotkey_listener` raises, set tray tooltip to `"⚠ hotkey error"` and
emit an error toast, but keep the tray running so the user can rebind via the
menu. Most of this is already in place; just polish the surfaced state.

---

## Rejected options

| Option | Why not |
|---|---|
| Replace pynput with `RegisterHotKey` for the trigger | No key-up event → kills hold mode. No priority gain over LL hooks. |
| Switch to the `keyboard` PyPI package | Same `WH_KEYBOARD_LL` underneath. Often wants admin elevation. Adds packaging risk. |
| Run AriasSTT elevated to outrank other hooks | LL hook order isn't strictly priority-based by elevation; security + UX cost; breaks the existing "elevated app refuses synthetic input" fallback story. |
| Custom kernel/driver hook | Out of scope for a tray app. |

---

## Sequencing

1. **P0** — ship today (default + presets + warning labels).
2. **P1** — next session (best UX win).
3. **P4** — cheap and orthogonal; lands when convenient.
4. **P3** — add once P4 is in place; together they cover both conflict classes.
5. **P2** — if/when push-to-talk demand actually materializes.
6. **P5** — polish along the way.

## Open questions

- Do we want a `mode` switch in the *menu* even before P2 lands? Probably no
  — leave the existing toggle behavior alone until hold mode is real.
- Should P1's live-capture also accept mouse side buttons (XButton1 / XButton2)?
  Worth doing if the capture dialog is generic; out of scope for the first cut.
- F-key only mode for laptops where Fn-row is hijacked by media keys —
  document, don't engineer around.

---

## References

- pynput global hotkeys: https://pynput.readthedocs.io/en/latest/keyboard.html#global-hotkeys
- Win32 `RegisterHotKey`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey
- `WH_KEYBOARD_LL` hook chain semantics: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexa
