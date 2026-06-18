---
id: 04-branding-icons
title: Branding & icon set
status: draft
target: v1.0.0
prd-section: §6.2 Feature D
companion-html: 04-branding-icons.html
last-updated: 2026-05-14
---

# Branding & icon set

> Replace the programmatic colored-dot tray icons with a proper designed
> icon family. Set the app-level icon used by the installer, shortcut,
> and taskbar.

## 1. Purpose

Programmatic dots ship today because they were free. v1.0 needs a real
visual identity to ship outside the tester circle. Three tray states +
one app icon, all bundled in the installer.

## 2. User stories

- As a user, I want the tray icon to feel like a real app, not a debug
  placeholder.
- As a user, I want to tell at a glance whether the app is idle,
  recording, or transcribing.
- As a user, I want the installer shortcut and taskbar to show the same
  icon.

## 3. Functional spec

### 3.1 Trigger
N/A — assets are static; loaded at startup and on state changes.

### 3.2 States (tray icon)
```
idle          → app-blue
push-to-talk  → red (recording)
meeting rec   → green (from module 03)
transcribing  → amber
loading       → busy spinner variant
```

### 3.3 Inputs
None — assets only.

### 3.4 Outputs
- Bundled `.ico` set for tray (16/32/48 px).
- Single `.ico` for installer + Start Menu shortcut.
- Optional `.png` versions for landing page and README.

### 3.5 Edge cases
- High-DPI scaling — ship 16/32/48 in the .ico container.
- Dark / light Windows taskbar background — single icon must work on
  both (no white-on-white, no black-on-black).

## 4. Visual design

> Concept sketch. Final art TBD — needs a visual design pass (PRD §9
> open decision).

```
   App icon              Tray (idle)        Tray (recording)
  ┌─────────┐            ┌──┐               ┌──┐
  │   ●▲    │            │● │               │● │  ← pulses
  │  Arias  │            └──┘               └──┘
  │   STT   │            blue               red
  └─────────┘
```

### 4.1 Tokens
- Idle: `#5B8CFF` (TBD — borrow from Arias brand once defined)
- Recording: `#ff6868` (matches overlay wave color)
- Meeting: `#00d27a` (matches module 03 meeting accent)
- Transcribing: `#f5a524` (amber)
- Background contrast: outline / glow so the icon reads on both light
  and dark taskbar.

### 4.2 Companion HTML
Open `04-branding-icons.html` to see the icon family at 16 / 32 / 48 /
128 px and hover the pulse animation.

## 5. Acceptance criteria

- [ ] Icon family designed (idle, recording, meeting, transcribing).
- [ ] `.ico` files bundled in the installer.
- [ ] PyInstaller spec references the new `.ico` for the executable.
- [ ] Inno Setup uses the new `.ico` for the Start Menu shortcut.
- [ ] Tray state changes swap to the correct icon without flicker.
- [ ] Icons read on both light and dark taskbar backgrounds.

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 | Who designs the icon family? (PRD §9) | y | |
| 2 | Animate the recording icon (pulse) or static? | n | |
| 3 | Reuse Arias master logo or design Auritus-specific mark? | y | |

## 7. Dependencies

- Modules: [03-meeting-recording](03-meeting-recording.md) (shares
  meeting accent color).
- Code: `dictate.py` → `ICON_IDLE`, `ICON_RECORDING`, `ICON_BUSY`.
- External: `installer.iss`, `Auritus.spec`.

## 8. Status log

- 2026-05-14 — created (draft)
