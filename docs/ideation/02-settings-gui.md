---
id: 02-settings-gui
title: Settings GUI window
status: draft
target: v1.0.0
prd-section: §6.2 Feature C
companion-html: 02-settings-gui.html
last-updated: 2026-05-14
---

# Settings GUI window

> One modal window that exposes every tunable currently scattered across
> the tray menu plus the knobs that aren't exposed at all (mic, overlay
> tokens, autostart).

## 1. Purpose

The tray menu is fine for power users but doesn't scale — too many nested
submenus, no live preview, no way to surface tunables that aren't
single-choice radios. Settings window is the home for all config in one
place.

## 2. User stories

- As a user, I want a single window where I can see every option, so I
  don't have to dig through nested tray submenus.
- As a user, I want overlay tweaks to live-preview as I drag sliders.
- As a user, I want my changes to persist immediately, not require an
  apply button.

## 3. Functional spec

### 3.1 Trigger
Tray → "Settings…" (new top-level item).

### 3.2 States
TBD — `closed | open | applying`. Settings live-apply, so `applying` is
brief (per-change).

### 3.3 Inputs
Form fields for: hotkey, cancel hotkey, mode, model, backend, mic device,
sounds toggle + volume, overlay tokens (opacity, fill, accent, border
width, corner radius, position), autostart toggle, open log folder
button.

### 3.4 Outputs
Writes to `config.json` on each change. Live-applies all visual changes
without restart.

### 3.5 Edge cases
- Cancel hotkey equals main hotkey → warn inline, cancel auto-disables.
- Mic device picker — selected device disappears between launches → fall
  back to default + toast.
- Backend = GPU with binary absent → greyed.

## 4. Visual design

```
┌────────────────────────────────────────────────────────┐
│  AriasSTT — Settings                              [×]  │
├────────────────────────────────────────────────────────┤
│  ▸ Input                                               │
│     Hotkey         [Ctrl+Alt+Space]      [Test]        │
│     Cancel hotkey  [Ctrl+F9]                           │
│     Mode           (•) Toggle  ( ) Hold                │
│     Mic device     [Realtek Audio (default)        ▾]  │
│                                                        │
│  ▸ Inference                                           │
│     Model          (•) medium.en   ( ) small.en  ...   │
│     Backend        (•) Auto  ( ) GPU  ( ) CPU          │
│                                                        │
│  ▸ Feedback                                            │
│     Sounds         [✓] On     Volume [────●──]         │
│     Overlay        [✓] Show                            │
│       Opacity       [──●─────]                         │
│       Position      (•) top  ( ) bottom  ( ) top-right │
│       (live preview pane on the right)                 │
│                                                        │
│  ▸ System                                              │
│     [✓] Start with Windows                             │
│     [ Open log folder ]                                │
│                                                        │
│  AriasSTT v0.3.0 — github.com/Nyavix/AriasSTT          │
└────────────────────────────────────────────────────────┘
W TBD (≈560) · H TBD (≈640)
```

### 4.1 Tokens
- Match existing overlay tokens by default.
- Surface form: TBD (system default vs custom dark panel).

### 4.2 Companion HTML
Open `02-settings-gui.html` to feel the panel switching, slider drag,
and live preview pane.

## 5. Acceptance criteria

- [ ] One tray menu entry ("Settings…") opens the window.
- [ ] Every existing tray submenu option is mirrored in the window.
- [ ] Mic device picker enumerates from `sounddevice` and persists.
- [ ] Overlay sliders update the live overlay in real time (no restart).
- [ ] Cancel-hotkey collision with main hotkey shows inline warning.
- [ ] Autostart checkbox writes/removes the Startup folder shortcut.
- [ ] Window opens on its own thread; tray icon stays responsive.

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 | Keep tray submenus once Settings exists, or collapse to just "Settings…"? | n | |
| 2 | Live preview pane embedded or floating? | n | |
| 3 | tk-native look or custom dark theme matching the overlay? | y | |

## 7. Dependencies

- Modules: [01-first-run-wizard](01-first-run-wizard.md) (shares
  `HotkeyCaptureDialog`).
- Code: `dictate.py` → `_build_menu`, `HotkeyCaptureDialog`,
  `RecordingOverlay`.

## 8. Status log

- 2026-05-14 — created (draft)
