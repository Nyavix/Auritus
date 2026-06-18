---
id: 01-first-run-wizard
title: First-run wizard
status: draft
target: v1.0.0
prd-section: §6.2 Feature A
companion-html: 01-first-run-wizard.html
last-updated: 2026-05-14
---

# First-run wizard

> Set up a working dictation flow in 60 seconds on a clean install, with
> zero config knowledge required.

## 1. Purpose

Removes the "guess what to do after install" gap. PRD success metric: new
user completes first successful dictation within 3 minutes of install.
Wizard handles the four decisions that matter on first launch (mic,
hotkey, model, backend) and writes them to `config.json`.

## 2. User stories

- As a non-technical user, I want a guided setup so I don't have to read
  the README to start dictating.
- As a power user, I want to skip / close the wizard and use my own
  config.

## 3. Functional spec

### 3.1 Trigger
Launch where `config.json` does not exist. Wizard opens once. Skipping or
closing writes the default config (same as today's first-launch
behavior).

### 3.2 States
TBD — fill in module work session.

### 3.3 Inputs
TBD.

### 3.4 Outputs
TBD — at minimum: `config.json` with `model`, `hotkey`, `cancel_hotkey`,
`mode`, `backend`, mic device.

### 3.5 Edge cases
TBD — no mic detected, GPU greyed when binary absent, user closes mid-flow.

## 4. Visual design

> Six screens (welcome → mic → hotkey → model → backend → done). ASCII
> below is placeholder; refine during module work.

```
┌────────────────────────────────────────┐
│  Auritus                              │
│  Step 1 of 5 — Welcome                 │
├────────────────────────────────────────┤
│                                        │
│  Welcome to Auritus.                  │
│  Let's set up in 60 seconds.           │
│                                        │
│                       [ Get started → ]│
└────────────────────────────────────────┘
W TBD · H TBD
```

### 4.1 Tokens
- TBD during module work.

### 4.2 Companion HTML
Open `01-first-run-wizard.html` for click-through.

## 5. Acceptance criteria

- [ ] Wizard opens automatically on launches where `config.json` is absent.
- [ ] All five steps render without errors and persist their selection.
- [ ] Closing the wizard at any step writes a usable default config.
- [ ] Mic test plays back a live level meter from the selected device.
- [ ] Hotkey capture re-uses `HotkeyCaptureDialog`.
- [ ] GPU backend choice is greyed when `whisper-server.exe` is absent.

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 | Show the cancel-hotkey step or default it silently? | n | |
| 2 | Skip-able by step or only via close button? | n | |
| 3 | Model download triggered inside the wizard or deferred to first dictation? | y | |

## 7. Dependencies

- Modules: [02-settings-gui](02-settings-gui.md) (shares `HotkeyCaptureDialog`).
- Code: `dictate.py` → `HotkeyCaptureDialog`, `load_user_config`.

## 8. Status log

- 2026-05-14 — created (draft)
