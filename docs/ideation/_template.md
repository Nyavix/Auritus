---
id: NN-kebab-name
title: Module Title
status: draft        # draft | locked | shipped
target: v1.0.0
prd-section: §6.2 Feature X
companion-html: NN-kebab-name.html   # or "none"
last-updated: YYYY-MM-DD
---

# Module Title

> One-sentence purpose. The thing this module exists to solve.

## 1. Purpose

What problem this module solves and for whom. Two or three sentences.

## 2. User stories

- As a [user], I want to [action], so that [outcome].
- As a [user], I want to [action], so that [outcome].

## 3. Functional spec

### 3.1 Trigger
How the module enters the foreground (hotkey, tray menu, fresh-install
detection, etc).

### 3.2 States
List every state and the transitions between them.

```
state-a --event--> state-b
state-b --event--> state-c
```

### 3.3 Inputs
What the user can do at each state (clicks, keys, form fields).

### 3.4 Outputs
What the module writes (config keys, files, notifications, logs).

### 3.5 Edge cases
- What if [unexpected condition]? → [response]
- What if [unexpected condition]? → [response]

## 4. Visual design

> ASCII mockup for layout. Companion `.html` for click-through feel.

```
┌────────────────────────────────┐
│  Module Title                  │
├────────────────────────────────┤
│  ...                           │
└────────────────────────────────┘
W [px] · H [px]
```

### 4.1 Tokens
- Background: `#xxxxxx`
- Accent: `#xxxxxx`
- Text: `#xxxxxx` / family / size
- Border: width [px] / color / radius [px]
- Motion: [duration / easing] for [event]

### 4.2 Companion HTML
Open `NN-kebab-name.html` in a browser to feel the transitions and
hover states.

## 5. Acceptance criteria

PRs cite this section. Each row is a binary check.

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## 6. Open questions

| # | Question | Blocking? | Resolution |
|---|----------|-----------|------------|
| 1 |          | y / n     |            |

## 7. Dependencies

- Other modules: [link]
- Code: [file / function]
- External: [library / asset]

## 8. Status log

- YYYY-MM-DD — created (draft)
