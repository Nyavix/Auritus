---
id: 03-meeting-recording
title: Meeting recording mode
status: draft
target: v1.0.0
prd-section: §6.2 Feature B
companion-html: 03-meeting-recording.html
last-updated: 2026-05-14
---

# Meeting recording mode

> Long-session capture that saves a timestamped, model-aware Markdown
> transcript to `Documents\AriasSTT\meetings\`.

## 1. Purpose

Dictation is push-to-talk for short bursts. Meeting mode is the opposite
— capture a 45-minute call passively, transcribe at the end, write to
disk. Different state, different overlay, separate hotkey.

## 2. User stories

- As a meeting attendee, I want to start a long recording with one
  hotkey and forget about it until the meeting ends.
- As a user, I want the final transcript saved as Markdown with
  timestamps so I can scan it later.
- As a user, I want to know at a glance whether a meeting recording is
  in progress (distinct overlay / tray state).

## 3. Functional spec

### 3.1 Trigger
- Separate hotkey, configurable. PRD default: `<ctrl>+<alt>+<shift>+<space>`.
- OR tray → "Start meeting recording".

### 3.2 States
```
idle → recording → transcribing → saved → idle
```
Cancel path TBD — does the cancel hotkey from module 00 apply here, or a
dedicated stop-without-save?

### 3.3 Inputs
- Start: hotkey or tray.
- Stop: same hotkey toggles off, or tray → "Stop & transcribe".

### 3.4 Outputs
File at `Documents\AriasSTT\meetings\YYYY-MM-DD_HH-MM.md` formatted as:

```markdown
# Meeting — 2026-05-10 14:32

**Duration:** 47m 12s
**Model:** medium.en · GPU (whisper.cpp Vulkan)

---

[00:00:00] Good morning everyone, let's get started.
[00:01:14] So the first item is the Q2 roadmap review...
```

Notification: "Meeting transcript saved → Documents\AriasSTT\meetings\…"
with a clickable "Open folder" action.

### 3.5 Edge cases
- Session exceeds `MEETING_MAX_MINUTES` (default 120) → auto-stop.
- Audio buffer >500 MB in memory → flush to temp file.
- Attempt to start a second meeting while one is active → error toast.
- App crash mid-recording → TBD (recover partial audio?).

## 4. Visual design

### Tray icon / overlay states
```
idle              ●  blue
push-to-talk rec  ●  red (existing)
meeting rec       ●  green + pulsing
transcribing      ●  amber + spinner
```

### Overlay during meeting recording
```
┌─────────────────────────────────────┐
│  ● Meeting recording   00:12:47     │
└─────────────────────────────────────┘
W 280 · H 48
```

### 4.1 Tokens
- New token: meeting accent `#00d27a` (green) — TBD final hex.
- Pulse: 1.2 s ease-in-out, opacity 0.6 → 1.0.

### 4.2 Companion HTML
Open `03-meeting-recording.html` to feel the state transitions and
pulsing dot.

## 5. Acceptance criteria

- [ ] Separate hotkey starts / stops the meeting session.
- [ ] Tray icon switches to the green meeting state during recording.
- [ ] Overlay shows live duration counter.
- [ ] Final transcript is saved to the documented path with the
      documented format (timestamp + model + body).
- [ ] Notification on save has an "Open folder" action.
- [ ] Auto-stop fires at `MEETING_MAX_MINUTES`.
- [ ] Two sessions cannot run concurrently.

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 | Does cancel hotkey discard a meeting, or only push-to-talk? | y | |
| 2 | Timestamp granularity — every utterance, every minute, or whisper segment? | y | |
| 3 | Auto-save partial transcript on crash recovery? | n | |
| 4 | Speaker labels — defer to v1.1 per PRD §9? | y (lean v1.1) | |

## 7. Dependencies

- Code: `dictate.py` → `Recorder`, `_do_transcribe`, overlay state machine.
- New constant: `MEETING_MAX_MINUTES`.
- New tray icon color.

## 8. Status log

- 2026-05-14 — created (draft)
