# Phase 4.1 — Verified Medication Appearance Descriptions

## Required Reading

Before making changes, read:

1. `rules.md`
2. `README.md`
3. `docs/architecture.md`
4. `prompts/phase4_1_medication_appearance.md`
5. `data/reconciliation/ready_demo.json`
6. `scripts/prepare_demo_data.py`
7. `medication/runtime.py`
8. `medication/reconciliation.py`
9. `medication/plan_builder.py`
10. `medication/runtime_service.py`
11. `ui/gradio_app.py`
12. all relevant tests

Treat `rules.md` as authoritative.

Write a concise implementation plan before modifying files.

---

## Context

Medication Copilot already supports:

- Verified medication plans
- Scheduled-dose tracking
- Natural-language text interaction
- Local voice transcription
- Deterministic medication resolution
- An accessible medication dashboard

Many older adults recognize medicines through visible characteristics such as:

- Color
- Shape
- Dosage form
- Transparency
- Size
- Imprint
- Packaging or container

This phase adds verified medication-appearance descriptions as an accessibility
and recall aid.

It does not implement image recognition or visual pill identification.

---

# Primary Objective

Display a concise, verified appearance description beneath each medicine name.

Example:

```text
Omega 3 — 2000 mg
Yellow, transparent softgel capsule.
```

The same description may also be shown in:

- The next-medicine card
- Today’s medication rows
- Confirmation dialogs
- Saved medication details
- Voice mutation confirmations
- Simplified-language output when useful

Appearance information must remain secondary to the medicine name and strength.

---

# Core Safety Rule

Medication appearance is a supporting memory aid only.

The application must never:

- Identify a medicine solely by color, shape, or appearance
- Tell a user to take a medicine because it looks similar
- Infer appearance from the medication name
- Generate appearance descriptions from general model knowledge
- Assume all manufacturers produce the same-looking medicine
- Treat a refill with changed appearance as automatically equivalent
- Resolve an ambiguous medication solely by visual description
- Present unverified visual characteristics as fact

The UI must include a concise disclaimer such as:

> Appearance can vary by manufacturer or refill. Check the label if a medicine
> looks different.

Do not repeat this warning under every card if that creates clutter. Place it
once near the schedule or medication details.

---

# Source of Appearance Data

Appearance information must come only from an explicit trusted source.

Allowed sources:

- `synthetic_reconciliation_profile`
- `synthetic_demo_data`
- `patient_confirmed`
- `caregiver_confirmed`
- `pharmacist_confirmed`
- `prescription_label_confirmed`

Not allowed:

- Model inference
- Medication-name inference
- Unverified internet knowledge
- Guessing from dosage form
- Automatic image interpretation in this phase

Every appearance record must have provenance.

---

# Data Model

Add a presentation-focused appearance object to reconciled medication-plan
entries.

Suggested structure:

```json
{
  "appearance": {
    "description": "Small, round, white tablet.",
    "color": ["white"],
    "shape": "round",
    "dosage_form": "tablet",
    "transparency": "opaque",
    "size": "small",
    "imprint": null,
    "special_features": [],
    "source": "synthetic_reconciliation_profile",
    "verification_status": "verified",
    "verified_by": "synthetic_caregiver",
    "verified_at": "2026-08-01T09:00:00-04:00"
  }
}
```

Not every field is required.

Allowed `verification_status` values:

- `verified`
- `unverified`
- `not_recorded`

Rules:

- Only `verified` descriptions may appear as factual patient-facing text.
- `unverified` descriptions may appear only in review mode with a clear label.
- `not_recorded` should result in no appearance description.
- Missing appearance data must not produce a guessed description.
- Preserve null values rather than inventing details.

If modifying the stable runtime schema would be too disruptive, add this as an
optional backward-compatible field with a default of `null`.

Do not make appearance mandatory for medication-plan validity or readiness.

---

# Curated Demo Data

Add verified synthetic appearance descriptions to the ready demo patient through
the reconciliation profile or official demo-data generation pipeline.

Do not hand-edit `data/runtime_patients/*.runtime.json`.

Suggested demo descriptions:

```text
Metoprolol succinate ER 100 mg
Small, round, white tablet.

Vitamin D3 1000 IU
Small, pale-yellow softgel capsule.

Metformin 500 mg
White, oval tablet.
```

These are synthetic demo descriptions and must be clearly sourced as such.

Do not claim that these descriptions represent every commercial version of the
medicine.

The unready patient’s source medications should not receive trusted appearance
descriptions unless they are explicitly present and verified.

---

# UI Requirements

## Today’s medication cards

Under the medicine name and strength, display:

```text
Small, pale-yellow softgel capsule.
```

Use a visually secondary but readable style.

Requirements:

- Strong text contrast
- Slightly smaller than the medicine name
- No low-opacity white or gray text
- No excessive icons
- No appearance description when not recorded
- Do not display raw JSON fields

## Next-medicine card

Show the verified appearance description below the medicine name and strength.

Example:

```text
Vitamin D3
1000 IU
Small, pale-yellow softgel capsule.

Scheduled for 1:00 PM
```

## Confirmation dialogs

For state-changing text or voice actions, optionally include the verified
appearance description to help the user confirm the medicine.

Example:

```text
Record Vitamin D3 1000 IU as taken?

Appearance saved in your plan:
Small, pale-yellow softgel capsule.

Scheduled for 1:00 PM
```

The name, strength, and scheduled dose remain authoritative.

Do not allow appearance alone to approve the action.

## Simplified-language mode

Use concise text:

```text
Vitamin D3, 1000 IU.
Pale-yellow softgel.
Scheduled for 1 PM.
```

Do not remove safety, readiness, ambiguity, or confirmation meaning.

## Accessibility

Ensure appearance text is:

- Screen-reader accessible
- Readable in normal and high-contrast modes
- Visible at 150% and 200% browser zoom
- Not represented only by colored shapes
- Available as text, not just an icon

---

# Resolver and Intent Rules

Do not change the deterministic medication resolver to identify medicines by
appearance in this phase.

The resolver may continue to use:

- Verified medication name
- Strength
- Patient-friendly name
- Aliases
- User labels
- Existing schedule labels

Appearance descriptions are display and confirmation aids only.

A request such as:

> “Did I take the yellow pill?”

must not automatically mutate state.

Safe behavior:

- If a manually verified alias such as `yellow pill` already exists and uniquely
  identifies one plan medicine, the existing alias resolver may handle it.
- Otherwise ask the user to choose from verified medication names.
- Do not dynamically match arbitrary colors or shapes against appearance fields
  for state-changing actions in this phase.

---

# Voice Interaction

Voice responses may mention a verified appearance description when it helps
confirmation.

Example:

> I found Vitamin D3, 1000 IU—the pale-yellow softgel in your saved plan. Do you
> want to record the 1:00 PM dose as taken?

Rules:

- TTS is not required.
- The transcript remains the user’s input.
- Appearance does not replace deterministic medication resolution.
- Appearance must not be used to silently correct a transcription.
- Voice mutations still require explicit confirmation.

---

# Appearance Mismatch Guidance

Add a deterministic informational response or UI note:

> Appearance can change between manufacturers or refills. If a medicine looks
> different from the saved description, check the prescription label and ask a
> pharmacist or caregiver before relying on appearance.

The app must not:

- Declare the medicine counterfeit
- Declare it unsafe
- Decide it is the wrong medicine
- Recommend taking or discarding it
- Compare pill images in this phase

---

# Privacy

Appearance metadata must remain local.

Do not:

- Send it to unrelated model prompts
- Include it in transcription prompts
- Store pill photographs
- Add image data
- Add external lookup services

Only include appearance in Gemma context when the user explicitly asks about
the saved description or when producing a confirmation response requires it.

Prefer deterministic templates rather than asking Gemma to describe the pill.

---

# Validation Rules

Add validation for the optional appearance object.

Requirements:

- `description` must be non-empty when verification status is `verified`
- `source` is required for verified data
- `verified_by` and `verified_at` are required when appropriate for the source
- `not_recorded` must not contain a factual description
- Empty strings must normalize to null or fail validation
- Appearance cannot affect readiness
- Appearance cannot create schedules
- Appearance cannot create aliases automatically
- Appearance cannot modify medication names or strengths

---

# Tests

Add tests for:

## Data model

- Verified appearance validates
- Appearance absent remains valid
- Unverified appearance does not display as fact
- Verified appearance without provenance fails
- `not_recorded` with a description fails
- Existing runtime files without appearance remain backward compatible

## Demo generation

- Appearance originates from reconciliation/demo source
- Runtime JSON is generated through the official pipeline
- No manual runtime editing is required
- Reset-demo restores appearance fields deterministically

## UI

- Next medicine shows verified appearance
- Today’s medicine card shows verified appearance
- Missing appearance hides the line cleanly
- Unready source medication does not appear as a verified visual aid
- High-contrast and large-text modes remain readable
- Appearance disclaimer is visible

## Mutation and safety

- Appearance alone cannot trigger a mutation
- “Yellow pill” remains ambiguous unless an explicit verified alias exists
- Confirmation still includes exact medication name, strength, time, and date
- Duplicate confirmation remains idempotent
- Existing safety refusals remain unchanged

## Voice regression

- Voice confirmation may display verified appearance
- Transcription is not corrected using appearance
- Appearance is not sent to the transcription provider
- Existing voice confirmation rules remain intact

## Regression

- All existing text, voice, readiness, reconciliation, and safety tests pass
- Existing data without appearance remains loadable
- No runtime schema break for optional data

---

# Documentation

Update:

- `README.md`
- `docs/architecture.md`
- `docs/demo_script.md`
- `docs/roadmap.md`
- `CONTRIBUTING.md`

Document:

- Appearance is optional
- Appearance is verified metadata
- It is a memory aid, not identification
- It may vary by manufacturer or refill
- The current demo uses synthetic descriptions
- Image recognition remains future work

Do not advertise pill recognition or visual identification as implemented.

---

# Acceptance Criteria

Phase 4.1 is complete only when:

1. Verified appearance descriptions display beneath medication names.
2. Appearance metadata has explicit provenance.
3. Missing data is not guessed.
4. Existing runtime patients without appearance remain valid.
5. Appearance does not affect readiness.
6. Appearance does not affect schedules.
7. Appearance does not become an automatic resolver.
8. State-changing actions still require exact medication resolution.
9. Appearance-only requests do not mutate data.
10. The UI includes a manufacturer/refill variability notice.
11. Demo reset regenerates appearance deterministically.
12. Text and voice workflows remain unchanged except for added display context.
13. No image recognition is implemented.
14. No external lookup is introduced.
15. All existing tests pass.

---

# Required Verification

Run:

```bash
pytest -m "not integration"
python -m compileall -q app.py medication gemma ui scripts evaluation voice
python app.py reset-demo
python app.py verify-demo
git diff --check
```

Manually test:

- Ready patient dashboard
- Next-medicine card
- Today’s medicine cards
- High-contrast mode
- Large-text mode
- Simplified-language mode
- Text mutation confirmation
- Voice mutation confirmation
- Unready patient
- Missing appearance description
- Appearance mismatch disclaimer

Reset demo data after mutation testing.

---

# Final Report

Report:

- Data-model approach
- Provenance rules
- Demo descriptions added
- UI locations updated
- Resolver behavior
- Voice behavior
- Files changed
- Tests added
- Test totals
- Manual checks
- Backward compatibility
- Known limitations

Do not begin image recognition or Phase 5.
