# Phase 3 — Medication Dashboard, Accessibility, and Demo UX

## Required Reading

Read completely before making any changes:

1. rules.md
2. README.md
3. docs/architecture.md
4. docs/demo_script.md
5. ui/gradio_app.py

Treat rules.md as authoritative.

This phase focuses ONLY on user experience.

Do NOT modify:

- medication logic
- reconciliation
- runtime schemas
- deterministic safety
- runtime services
- routing semantics
- persistence
- runtime JSON structure

The backend is feature complete.

---

# Goal

Transform the existing Gradio application into a polished medication dashboard
designed specifically for older adults.

The application should feel like a real healthcare product rather than a chatbot.

Every design decision should prioritize:

- clarity
- accessibility
- confidence
- simplicity

---

# Design Principles

Design for:

- older adults
- caregivers
- first-time users
- low technical confidence

Avoid:

- clutter
- dense text
- developer terminology
- hidden functionality
- tiny controls

The interface should communicate:

"I know what medicine I need."

within three seconds.

---

# Dashboard Layout

The dashboard should become the default landing screen.

Example structure:

----------------------------------------------------

👵 Elena Rivera

🟢 Medication Plan Verified

Today's Date

Friday, August 1

----------------------------------

NEXT MEDICINE

Vitamin D3

1:00 PM

Large prominent card

----------------------------------

Today's Progress

██████░░░░

1 / 3 doses completed

----------------------------------

Today's Medicines

✓ Metoprolol
○ Vitamin D3
○ Metformin

----------------------------------

Quick Actions

[✓ Mark Next Dose Taken]

[🗣 Repeat Last Answer]

[📋 Today's Schedule]

----------------------------------

Ask Medication Copilot

[text box]

[Ask]

----------------------------------

Conversation

...

----------------------------------------------------

The dashboard should always remain visible.

The conversation should never take over the screen.

---

# Patient Summary Card

Create a top summary card showing:

- patient name
- verification status
- local date
- readiness state

Use color only as an enhancement.

Never rely only on color.

Example:

🟢 Verified

instead of only a green box.

---

# Next Medication Card

This should be the visual focus.

Display:

Medication

Strength

Scheduled time

Purpose (if available)

Current status

If overdue:

Display a clearly visible overdue badge.

Do not alarm the user.

---

# Progress Section

Create a visual progress bar.

Display:

completed doses

scheduled doses

remaining doses

Progress should be calculated from runtime dose logs.

Never infer completion.

---

# Today's Schedule

Display today's medicines as large cards.

Each card should show:

Medication

Strength

Scheduled time

Status

Taken time (if recorded)

PRN medicines should be visually separated.

---

# Large Typography

Use noticeably larger fonts than standard Gradio defaults.

Important information:

- medication names
- next dose
- action buttons

should be immediately readable.

---

# High Contrast

Design for:

- reduced vision
- bright environments

Use strong contrast.

Avoid light gray text.

Avoid low-opacity UI.

---

# Oversized Buttons

Buttons should be easy to press.

Important buttons:

Mark Taken

Repeat Last Answer

Today's Schedule

Refresh

should all be visually prominent.

---

# Quick Actions

Add one-click buttons.

Required:

✓ Mark Next Dose Taken

🗣 Repeat Last Answer

📋 Show Today's Medicines

🕒 What Comes Next?

History

These buttons should call the existing backend.

Do not duplicate backend logic.

---

# Repeat Last Answer

Store the most recent assistant response.

One click should replay it inside the conversation.

This prepares the architecture for future voice output.

Do not implement text-to-speech.

Only repeat the last assistant message.

---

# Simplified Language Mode

Add a toggle:

Simplified Language

OFF / ON

When enabled:

Responses should be shorter.

Prefer:

"Take Vitamin D3 at 1 PM."

instead of long explanations.

Use the existing backend.

Do not change medication facts.

Only adjust presentation.

---

# Conversation Area

Retain chat.

But:

the dashboard is primary.

Conversation is secondary.

Messages should be easy to distinguish.

Show timestamps if available.

---

# Accessibility

Add support for:

Large text

High contrast

Simplified language

Future voice support placeholder

These settings should persist for the session.

---

# Session State

Maintain:

selected patient

conversation

last assistant answer

simplified mode

debug visibility

within the current Gradio session.

---

# Debug Panel

Keep the existing debug panel.

Move it into a collapsible accordion.

Default:

collapsed.

Developers can inspect:

intent

resolver

tool output

latency

clock

No chain-of-thought should ever be displayed.

---

# Visual Polish

Improve spacing.

Improve alignment.

Consistent margins.

Consistent typography.

Consistent icons.

Avoid emoji overload.

Use subtle section separators.

---

# Responsive Layout

The interface should remain usable on:

laptop

tablet

smaller browser windows

Avoid fixed widths.

---

# Existing Backend

Do NOT rewrite backend code.

Use the existing runtime services.

The UI should become a better presentation layer.

---

# Testing

Verify:

ready patient

unready patient

mark taken

repeat last answer

today schedule

next dose

history

unsafe request

ambiguous request

simplified mode

All should continue using the existing backend.

---

# Acceptance Criteria

The application should feel like a medication dashboard.

The first screen should answer:

"What medicine do I need?"

without asking the user to type.

The dashboard must remain visible while chatting.

Progress should update correctly.

One-click actions should call the backend.

No backend behavior should change.

No runtime schemas should change.

No safety rules should change.

The application should be demonstrably easier for older adults to use.

---

# Final Report

Report:

- implementation approach
- UI structure
- new Gradio components
- accessibility improvements
- session-state additions
- files changed
- screenshots (if generated)
- manual testing performed
- known limitations

Do not implement voice or image input in this phase.
