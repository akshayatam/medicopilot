# Medication Copilot Data Rules

## Purpose

This document defines the data, safety, reconciliation, and implementation rules for converting Synthea FHIR records into a safe, usable dataset for an offline medication copilot for older adults and caregivers.

The application is a medication-navigation and adherence-support tool. It is not a diagnostic, prescribing, treatment, interaction-checking, or dose-adjustment system.

These rules apply to:

- Synthea FHIR ingestion
- Medication normalization
- Medication reconciliation
- Reminder-plan creation
- Dose-log generation
- Allergy handling
- Condition handling
- AI context construction
- UI behavior
- Validation and testing

---

## 1. Core Safety Principles

### 1.1 Source data is not automatically a verified medication plan

FHIR resources are imported clinical records. They must not automatically become the patient's daily medication plan.

The system must distinguish between:

1. **Source clinical record**
   - Imported from Synthea FHIR
   - Preserves original status, codes, dates, and provenance
   - May contain stale, duplicated, conflicting, incomplete, or encounter-specific records

2. **Reconciled medication plan**
   - Contains only medicines confirmed for current use
   - Contains verified reminder schedules
   - Contains user-facing names and aliases
   - Is the only source used for daily reminder and dose-status features

3. **Adherence ledger**
   - Contains app-generated or explicitly simulated dose events
   - Records scheduled, taken, late, missed, or unknown doses
   - Must not be inferred directly from MedicationRequest

The application must never treat the source FHIR medication list as equivalent to a confirmed current medication list.

### 1.2 The model is never the source of truth

The AI model may:

- Interpret a natural-language request
- Select an approved application action
- Ask for clarification
- Produce a user-friendly rendering of deterministic tool output

The AI model must not:

- Invent medication names
- Invent strengths
- Invent exact reminder times
- Invent meal instructions
- Infer whether a medication should be continued
- Decide which duplicate order is correct
- Infer that an ordered medication was taken
- Diagnose a condition
- Recommend starting, stopping, combining, skipping, replacing, or changing medication
- Resolve medication conflicts clinically

All factual answers must come from validated local data and deterministic application functions.

---

## 2. Patient Selection Rules

### 2.1 Minimum age

Only patients aged 60 or older at the configured dataset reference date may be included.

The pipeline must:

- Generate Synthea patients with an age range such as `60-110`
- Recalculate age from `Patient.birthDate`
- Apply an independent converter-side minimum-age check
- Skip records with missing or invalid birth dates
- Store the reference date used to calculate age

Recommended fields:

```json
{
  "birth_date": "1962-11-04",
  "age_at_dataset_reference_date": 63
}
```

### 2.2 Alive-patient filtering

When generating data intended to represent a current medication plan, prefer living patients.

The converter must not assume that a patient is alive merely because a FHIR bundle exists. Use Synthea generation settings and validate available death fields when present.

### 2.3 Patient identifiers

Retain:

- Synthetic patient UUID
- Display name
- Birth date
- Age at reference date
- Gender when available
- Preferred language
- Timezone when known

Exclude from the medication-copilot output unless explicitly needed:

- Synthetic SSN
- Passport number
- Driver's-license number
- Exact street address
- Phone number
- Exact latitude and longitude

---

## 3. Required Data-Layer Separation

The final application data model should follow this logical structure:

```json
{
  "source_record": {},
  "medication_plan": {},
  "dose_logs": []
}
```

A single-file implementation may physically store these together, but the code must preserve the conceptual separation.

### 3.1 Source record

Contains:

- Patient profile
- FHIR medication orders
- Conditions
- Allergies
- Selected clinical administrations
- Provenance
- Import warnings

### 3.2 Medication plan

Contains:

- Confirmed current medicines
- Verified reminder schedules
- User-facing names
- Patient or caregiver aliases
- Reconciliation status
- Verification metadata
- Inclusion status for daily reminders

### 3.3 Dose logs

Contains:

- Scheduled dose instances
- App-recorded adherence events
- Explicitly simulated adherence events
- Source and provenance for each event

---

## 4. MedicationRequest Import Rules

### 4.1 Preserve source fields

For every imported MedicationRequest, preserve when available:

- FHIR resource ID
- RxNorm code
- Code system
- Raw medication display
- Medication name
- Strength
- Dose form
- Status
- Intent
- Authored date
- Validity period
- Requester
- Encounter reference
- Linked reason references
- Dosage instructions
- Exact FHIR-supplied times
- PRN/as-needed status
- Provenance

### 4.2 Separate FHIR status from current-use status

Do not map:

```json
"fhir_status": "active"
```

directly to:

```json
"currently_taken": true
```

Use separate fields:

```json
{
  "fhir_status": "active",
  "current_use_status": "unverified",
  "included_in_daily_plan": false
}
```

Allowed `current_use_status` values:

- `confirmed_current`
- `unverified`
- `historical`
- `discontinued`
- `conflicting`

Only `confirmed_current` medicines may be included in the daily reminder plan.

### 4.3 Old active orders

A MedicationRequest may remain marked active even when authored many years ago.

The importer must add a non-clinical warning when an active order is older than a configurable threshold.

Example:

```json
{
  "validation_flags": [
    "old_active_order"
  ]
}
```

The system must not automatically discontinue it.

### 4.4 Missing dosage instructions

When dosage instructions are missing:

```json
{
  "schedule_type": "unknown",
  "has_exact_reminder_time": false,
  "reconciliation_status": "needs_review"
}
```

The system must not invent a schedule.

### 4.5 Missing reason or purpose

When a medication lacks a linked reason:

```json
{
  "purpose_labels": [],
  "purpose_source": "not_recorded"
}
```

The system must not infer a prescribed purpose from general drug knowledge and present it as source-record fact.

---

## 5. Medication Name Normalization

### 5.1 Preserve raw display

Always retain the original FHIR/RxNorm display:

```json
{
  "raw_display": "24 HR metoprolol succinate 100 MG Extended Release Oral Tablet"
}
```

### 5.2 Add normalized fields separately

Use separate normalized fields:

```json
{
  "patient_friendly_name": "Metoprolol succinate ER",
  "ingredients": [
    {
      "name": "metoprolol succinate",
      "strength": "100 mg"
    }
  ],
  "dose_form": "extended-release oral tablet",
  "brand_name": null
}
```

### 5.3 Do not rely only on regex parsing

Medication display strings may contain:

- Multiple ingredients
- Concentrations
- Units per mL
- Brand names
- Extended-release descriptors
- Device or spray forms
- Combination products

Prefer:

1. Structured FHIR fields
2. RxNorm code-based local normalization
3. Conservative parsing
4. Raw-display fallback

If parsing is uncertain, retain null normalized fields and add:

```json
{
  "validation_flags": [
    "medication_display_not_fully_normalized"
  ]
}
```

---

## 6. PRN and As-Needed Medication Rules

### 6.1 Never generate a fixed reminder for PRN medication

If FHIR indicates `asNeededBoolean=true`, `asNeededCodeableConcept`, or equivalent text such as “Take as needed”:

```json
{
  "schedule_type": "as_needed",
  "reminder_schedule": []
}
```

### 6.2 Preserve source instruction

Store:

```json
{
  "source_instruction": "Take as needed."
}
```

### 6.3 Require review

All imported PRN records should receive:

```json
{
  "requires_human_verification": true,
  "validation_flags": [
    "prn_instruction_requires_review"
  ]
}
```

The system must not clinically judge whether PRN use is appropriate for that medicine.

### 6.4 PRN interaction behavior

The app may:

- Show that a medicine is recorded as as-needed
- Show the saved source instruction
- Record a user-reported administration
- Ask the user to verify the plan

The app must not:

- Tell the user whether they should take the PRN medicine now
- Recommend a maximum dose unless explicitly stored in a verified record
- Infer symptom-based use instructions

---

## 7. Schedule Rules

### 7.1 Frequency is not an exact time

The following:

```json
{
  "frequency": 1,
  "period": 1,
  "period_unit": "d"
}
```

means once daily. It does not specify morning, evening, before food, after food, or an exact clock time.

Do not generate `08:00` or `20:00` from frequency alone.

### 7.2 Exact times

Only include an exact source-derived schedule when FHIR explicitly supplies it, such as `timing.repeat.timeOfDay`.

Example:

```json
{
  "time": "08:00",
  "source": "FHIR dosageInstruction.timing.repeat.timeOfDay",
  "verified": true
}
```

### 7.3 Meal context

Do not infer:

- Before breakfast
- After breakfast
- With lunch
- After dinner
- Empty stomach

Meal context must be:

- Explicitly present in source instructions, or
- Added through a separate synthetic reconciliation profile

### 7.4 Synthetic schedule enrichment

Synthetic reminder schedules must be clearly marked:

```json
{
  "time": "08:00",
  "period": "morning",
  "meal_context": null,
  "source": "synthetic_reconciliation_profile",
  "verified": true,
  "verified_by": "synthetic_caregiver",
  "verified_at": "2026-07-28T14:00:00-04:00"
}
```

Never overwrite the FHIR-derived dosage instruction with synthetic enrichment.

---

## 8. Medication Reconciliation Rules

### 8.1 Every imported medication starts unverified

Default:

```json
{
  "current_use_status": "unverified",
  "included_in_daily_plan": false,
  "reconciliation_status": "needs_review"
}
```

### 8.2 Detect non-clinical conflict patterns

The code should detect and flag:

- `same_normalized_ingredient_multiple_strengths`
- `possible_duplicate_order`
- `same_ingredient_multiple_orders`
- `old_active_order`
- `missing_dosage_instruction`
- `missing_reason`
- `prn_instruction_requires_review`
- `medication_display_not_fully_normalized`
- `possible_replacement_or_renewal`
- `multiple_orders_same_therapeutic_group`

These flags are for review only. They must not produce clinical recommendations.

### 8.3 Duplicate strengths

If two orders contain the same normalized ingredient but different strengths:

```json
{
  "reconciliation_status": "needs_review",
  "reconciliation_flags": [
    {
      "type": "same_normalized_ingredient_multiple_strengths",
      "related_medication_ids": [
        "med_a",
        "med_b"
      ]
    }
  ]
}
```

Do not choose one automatically.

### 8.4 Potential replacement medicines

If medicines may represent replacements or alternatives, mark them for review.

The application must not state:

- Which one is newer clinically
- Which one should be stopped
- Which one is safer
- Which combination is appropriate

### 8.5 Reconciliation completion

A medication may become `confirmed_current` only through an explicit reconciliation record.

Example:

```json
{
  "current_use_status": "confirmed_current",
  "included_in_daily_plan": true,
  "reconciliation_status": "verified",
  "verified_by": "synthetic_caregiver",
  "verified_at": "2026-07-28T14:00:00-04:00"
}
```

---

## 9. Allergy Rules

### 9.1 Missing AllergyIntolerance resource

When no structured AllergyIntolerance resource exists:

```json
{
  "allergies": [],
  "allergy_status": "not_recorded"
}
```

Never convert absence of resources into “no allergies.”

### 9.2 Explicit no-known-allergy assertion

Only use:

```json
{
  "allergies": [],
  "allergy_status": "no_known_allergies_explicitly_recorded"
}
```

when the FHIR record contains an explicit structured no-known-allergy assertion.

### 9.3 Recorded allergies

When allergies exist, preserve:

- Substance
- Code
- Code system
- Clinical status
- Verification status
- Type
- Category
- Criticality
- Recorded date
- Reactions
- Manifestations
- Severity
- Provenance

### 9.4 AI behavior around allergies

The app may:

- State whether structured allergy data is recorded
- Show the saved allergy list
- State that allergy information is not recorded

The app must not:

- Infer allergies
- Declare a medicine safe because no allergy resource exists
- Perform interaction or allergy-risk assessment

---

## 10. Condition Rules

### 10.1 Categorize conditions

Conditions should be separated into:

```json
{
  "clinical_conditions": [],
  "historical_conditions": [],
  "social_context": [],
  "administrative_flags": []
}
```

### 10.2 Do not treat every active Condition as a current diagnosis

FHIR Condition may contain:

- Clinical disorders
- Historical situations
- Social findings
- Administrative reminders
- Screening status
- Employment or education information

Do not flatten these into one clinical list.

### 10.3 Sensitive-condition minimization

Sensitive conditions or social findings should not automatically be included in AI context or patient-facing medication views.

Add visibility metadata:

```json
{
  "visibility": {
    "include_in_medication_context": false,
    "show_in_patient_ui": false
  }
}
```

Examples requiring restrictive defaults include:

- Intimate partner abuse
- Criminal-record history
- Substance-use history
- Sensitive social circumstances

### 10.4 Minimum context principle

For routine medication questions, Gemma should receive only:

- Confirmed current medicines
- Verified schedules
- Relevant aliases
- Dose logs
- Allergy status
- Explicitly linked purpose labels when useful

Do not send the full condition history unless the requested feature genuinely requires it.

---

## 11. MedicationAdministration Rules

### 11.1 Keep separate from home adherence logs

FHIR MedicationAdministration represents a clinical administration event. It may come from an inpatient, emergency, clinic, or procedure encounter.

Store it separately:

```json
{
  "clinical_administrations": [
    {
      "medication_reference": "...",
      "effective_at": "...",
      "status": "completed",
      "encounter_reference": "...",
      "source": "Synthea FHIR MedicationAdministration",
      "eligible_as_home_adherence_log": false
    }
  ]
}
```

### 11.2 Never merge automatically into dose_logs

`MedicationAdministration` must not automatically become an app adherence record.

Only app-recorded or explicitly simulated home events belong in `dose_logs`.

---

## 12. Dose-Log Rules

### 12.1 Allowed statuses

Use a strict enum:

- `upcoming`
- `due`
- `taken`
- `taken_late`
- `missed`
- `skipped_by_user`
- `unknown`

### 12.2 Cross-field rules

- `taken` requires `taken_at`
- `taken_late` requires `taken_at`
- `upcoming` requires `taken_at = null`
- `due` requires `taken_at = null`
- `missed` requires `taken_at = null`
- `unknown` should not claim whether the medicine was taken
- `skipped_by_user` means only that the user recorded it as not taken; it is not a clinical instruction

### 12.3 Provenance

Every dose log must contain:

```json
{
  "source": "app_event"
}
```

or:

```json
{
  "source": "synthetic_adherence_simulation"
}
```

### 12.4 Scheduled-dose generation

Dose instances may only be generated from medicines that satisfy all of the following:

- `current_use_status == "confirmed_current"`
- `included_in_daily_plan == true`
- Schedule status is verified
- Medication is not PRN
- At least one reminder time exists

### 12.5 Reproducible simulation

Synthetic adherence generation must:

- Use a configurable random seed
- Store generation parameters
- Avoid claiming simulated rates are real-world adherence statistics
- Produce deterministic outputs when rerun with the same seed

---

## 13. Caregiver and Accessibility Rules

### 13.1 Do not infer a family caregiver from CareTeam

FHIR CareTeam may include:

- Patient
- Clinicians
- Healthcare organizations
- Other care participants

It does not necessarily identify a family caregiver.

Default:

```json
{
  "caregiver": null
}
```

### 13.2 Application support profile

Store app-specific support settings separately:

```json
{
  "support_profile": {
    "caregiver": null,
    "preferred_response_language": "en-US",
    "accessibility": {
      "large_text": true,
      "high_contrast": true,
      "voice_enabled": false
    },
    "confirmation_style": "explicit"
  }
}
```

### 13.3 Explicit confirmation

Actions that modify adherence state should require an explicit confirmation step when ambiguity exists.

Examples:

- “Mark my tablet as taken” must ask which tablet
- “I took it” must ask for clarification if multiple medicines are plausible
- Duplicate logs must be prevented

---

## 14. Import Readiness Rules

Every converted patient should include:

```json
{
  "import_summary": {
    "ready_for_medication_tracking": false,
    "blocking_issues": [],
    "warnings": []
  }
}
```

### 14.1 Blocking issues

Examples:

- `no_confirmed_current_medication_list`
- `no_verified_medication_schedule`
- `patient_below_minimum_age`
- `invalid_birth_date`
- `all_current_medications_unverified`
- `unresolved_medication_conflicts`

### 14.2 Warnings

Examples:

- `allergy_status_not_recorded`
- `multiple_possible_duplicate_medications`
- `historical_orders_still_marked_active`
- `missing_dosage_instructions`
- `missing_medication_reasons`
- `sensitive_conditions_excluded_from_ai_context`

### 14.3 Ready-state requirements

`ready_for_medication_tracking` may be true only when:

- At least one medicine is `confirmed_current`
- Every included medicine has a verified schedule
- No unresolved blocking conflict affects included medicines
- Timezone is known
- Dose-log generation rules can run deterministically

---

## 15. AI Context Rules

### 15.1 Build a minimal context object

Do not pass the whole converted patient JSON to Gemma.

Construct a purpose-built object such as:

```json
{
  "patient": {
    "preferred_language": "en-US",
    "timezone": "America/New_York"
  },
  "confirmed_medications": [],
  "verified_schedules": [],
  "recent_dose_logs": [],
  "allergy_status": "not_recorded"
}
```

### 15.2 Exclude by default

Do not include:

- Claims
- ExplanationOfBenefit
- Financial data
- Exact address
- Phone number
- SSN-like identifiers
- Entire encounter history
- Entire observation history
- Sensitive social conditions
- Base64 clinical notes
- DiagnosticReport or DocumentReference content
- Model chain-of-thought

### 15.3 Grounded response rules

The response must use phrases such as:

- “According to your saved medication plan...”
- “Your local record shows...”
- “This medicine was logged as taken at...”
- “The allergy status is not recorded in the local file.”

Avoid:

- “You should take...”
- “It is safe to...”
- “This medication treats...”, unless that purpose is explicitly present in the verified record
- “You have no allergies” when status is `not_recorded`

---

## 16. Safety Refusal Rules

The following requests must not trigger medication changes or treatment advice:

- “Should I double my dose?”
- “Can I stop this medicine?”
- “Can I take these medicines together?”
- “Which medicine should I take for this symptom?”
- “Can I replace this tablet with another?”
- “I missed yesterday. What should I do?”
- “Is this safe with my kidney disease?”
- “How much insulin should I take?”

Safe response pattern:

> I can help you review your saved medication schedule and dose history, but I cannot recommend medication changes or treatment. Please contact a clinician or pharmacist.

For overdose, accidental ingestion, or emergency language, use the application's emergency-escalation policy. Do not perform open-ended diagnosis or dosing guidance.

---

## 17. Validation Rules

Use Pydantic or an equivalent schema validator.

### 17.1 Allergy validation

- If `allergy_status == "not_recorded"`, `allergies` must be empty
- If `allergy_status == "recorded"`, `allergies` must not be empty
- If `allergy_status == "no_known_allergies_explicitly_recorded"`, `allergies` must be empty

### 17.2 Medication-plan validation

- If `included_in_daily_plan == true`, then `current_use_status == "confirmed_current"`
- If `included_in_daily_plan == true`, reconciliation status must be verified
- If reminder schedule is non-empty, schedule verification metadata is required
- If `schedule_type == "as_needed"`, fixed reminder schedule must be empty
- If exact schedule is absent, the application must not calculate a next dose

### 17.3 Dose-log validation

- Taken statuses require `taken_at`
- Non-taken statuses must not contain `taken_at`
- `medication_id` must reference a valid medication
- Duplicate scheduled instances must be rejected
- Duplicate “mark taken” operations must not create duplicate logs

### 17.4 Provenance validation

Every derived or synthetic field must state its source.

Examples:

- `Synthea FHIR MedicationRequest`
- `FHIR dosageInstruction.timing.repeat.timeOfDay`
- `synthetic_reconciliation_profile`
- `synthetic_adherence_simulation`
- `app_event`

---

## 18. Current Codebase Architecture

```text
├── app.py
├── config.py
├── CONTRIBUTING.md
├── data
│   ├── evaluation_cases.jsonl
│   ├── reconciliation
│   │   ├── ready_demo.json
│   │   └── unready_demo.json
│   ├── runtime_patients
│   │   ├── ready.runtime.json
│   │   └── unready.runtime.json
│   └── synthetic_patient.json
├── docs
│   ├── architecture.md
│   ├── demo_script.md
│   ├── phase2_test_report.md
│   └── roadmap.md
├── evaluation
│   ├── evaluate.py
│   └── __init__.py
├── gemma
│   ├── client.py
│   ├── __init__.py
│   ├── intent_router.py
│   ├── orchestrator.py
│   ├── patient_qa.py
│   ├── prompts.py
│   ├── response_parser.py
│   └── schemas.py
├── main.py
├── medication
│   ├── adherence_simulator.py
│   ├── clock.py
│   ├── fhir_converter.py
│   ├── health.py
│   ├── __init__.py
│   ├── models.py
│   ├── normalization.py
│   ├── patient_data_service.py
│   ├── patient_records.py
│   ├── plan_builder.py
│   ├── reconciliation.py
│   ├── repository.py
│   ├── resolver.py
│   ├── runtime.py
│   ├── runtime_repository.py
│   ├── runtime_service.py
│   ├── safety.py
│   ├── schemas.py
│   ├── service.py
│   ├── time_resolver.py
│   └── validators.py
├── prompts
│   ├── phase2_5_demo_preparation.md
│   ├── phase2_integration.md
│   └── phase3_ui_accessibility.md
├── pyproject.toml
├── README.md
├── requirements.txt
├── rules.md
├── scripts
│   ├── convert_synthea_fhir.py
│   ├── demo_management.py
│   └── prepare_demo_data.py
├── tests
│   ├── conftest.py
│   ├── test_client.py
│   ├── test_demo_management.py
│   ├── test_intent_parser.py
│   ├── test_orchestrator.py
│   ├── test_patient_records.py
│   ├── test_phase2_integration.py
│   ├── test_pipeline_rules.py
│   ├── test_repository.py
│   ├── test_safety.py
│   └── test_service.py
├── ui
│   ├── api.py
│   └── __init__.py
├── frontend
│   ├── src
│   ├── package.json
│   └── vite.config.ts
└── uv.lock

```

### 18.1 Recommended processing pipeline

```text
Synthea FHIR
    ↓
FHIR conversion
    ↓
Source-record validation
    ↓
Medication normalization
    ↓
Conflict detection
    ↓
Synthetic reconciliation profile
    ↓
Verified medication plan
    ↓
Scheduled dose generation
    ↓
Synthetic/app adherence events
    ↓
Minimal AI context
```

---

## 19. Supported CLI Commands

```bash
python app.py serve
```

Launch the built React interface and local FastAPI server.

```bash
python app.py ask --patient demo-ready-001 "What medicine comes next?"
```

Run a natural-language medication query.

```bash
python app.py health
```

Display runtime health.

```bash
python app.py verify-demo
```

Verify demo integrity.

```bash
python app.py verify-demo --require-model
```

Verify demo and require a working local Gemma model.

```bash
python app.py reset-demo
```

Restore deterministic runtime demo data.

```bash
python app.py list-patients
```

List runtime patients.

```bash
python app.py patient-status demo-ready-001
```

Show readiness and validation status.

---

## 20. Test Cases the Agent Must Add

### 20.1 Allergy tests

- No AllergyIntolerance resource → `not_recorded`
- Explicit no-known-allergy resource → explicit no-known status
- Recorded allergy with reaction
- Allergy status inconsistent with list → validation failure

### 20.2 Medication tests

- Active FHIR order remains `unverified`
- Completed order is not included in current plan
- Same ingredient, two strengths → conflict flag
- Missing dosage → review flag
- PRN medicine → no fixed schedule
- Frequency without exact time → no invented time
- Exact FHIR time → retained with provenance
- Complex combination medication → raw display preserved
- Unparseable display → normalization warning

### 20.3 Plan tests

- Unverified medication cannot enter daily plan
- Verified medicine without schedule cannot enter reminder plan
- PRN medicine cannot receive recurring reminder
- Conflicting medicines block readiness
- Timezone required for scheduled dose generation

### 20.4 Dose-log tests

- Taken requires `taken_at`
- Upcoming cannot have `taken_at`
- Duplicate mark-taken is idempotent
- Dose logs are generated only from verified schedules
- Same seed produces same synthetic adherence output

### 20.5 Privacy tests

- Sensitive social conditions excluded from AI context
- Exact address excluded
- Claims and billing records excluded
- Full raw FHIR bundle never passed to Gemma

---

## 21. Acceptance Criteria

The implementation is acceptable only when:

1. Patients under 60 are skipped.
2. Missing allergy resources produce `not_recorded`, never “no allergies.”
3. PRN medicines never receive fixed schedules.
4. Frequency-only instructions never create exact clock times.
5. Imported active orders remain unverified until reconciled.
6. Duplicate or conflicting medication records are flagged, not resolved clinically.
7. Only confirmed current medicines enter the daily plan.
8. Dose logs are not inferred from MedicationRequest.
9. Clinical MedicationAdministration events remain separate from home adherence logs.
10. Sensitive conditions are excluded from routine AI context.
11. Every synthetic or derived field includes provenance.
12. The AI receives only minimal, purpose-specific context.
13. The app can answer “what is next?” only when a verified schedule exists.
14. The app can answer “did I take it?” only from app/simulated dose logs.
15. The app asks for clarification instead of guessing.
16. The application never provides diagnosis, treatment, interaction, or dose-change advice.
17. All cross-field validation tests pass.
18. The converted patient includes readiness status, blocking issues, and warnings.

---

## 22. Agent Development Rules

Before modifying code:

1. Inspect the existing implementation.
2. Reuse existing runtime services whenever possible.
3. Do not duplicate medication logic.
4. Preserve deterministic behavior.
5. Preserve runtime schemas.
6. Preserve reconciliation behavior.
7. Preserve readiness behavior.
8. Preserve safety guardrails.
9. Preserve idempotent mutations.
10. Add regression tests for every safety-sensitive change.
11. Run the complete non-live test suite.
12. Report unsupported situations instead of guessing.
13. Never claim live-model behavior unless actually tested.
14. Clearly list every modified file.
15. Treat this document as the project's authoritative specification.

---

## 23. Voice Interaction Rules

Voice is only an alternative input/output method.

It is never a source of medication truth.

### Speech Input

Audio must be processed locally.

Voice-derived actions must pass through:

Speech Recognition

↓

Intent Router

↓

Schema Validation

↓

Deterministic Medication Resolver

↓

Runtime Service

↓

Grounded Response

Voice must never bypass deterministic validation.

### Confirmation

State-changing actions require explicit confirmation.

Example:

"I understood:

Record the 1:00 PM Vitamin D3 dose as taken.

Should I continue?"

Only after confirmation may the runtime service mutate dose logs.

### Spoken Output

Speech synthesis must only read deterministic grounded responses.

It must never speak:

- chain of thought
- debug output
- raw FHIR
- internal prompts

Safety refusals must be spoken exactly as generated.

### Low Confidence

Uncertain transcription must never mutate medication data.

Instead:

"I didn't understand which medicine you meant."

The application should request clarification.

---

## User Interface Rules

The UI is a presentation layer only.

It must not contain medication logic.

The dashboard should always display:

- patient name
- readiness status
- next medication
- today's progress
- today's medication schedule

The UI may cache presentation state only.

The UI must always reload medication state from the runtime service after any mutation.

One-click actions must invoke existing runtime APIs.

The UI must never calculate medication status itself.

Accessibility remains a primary design goal.

Preferred defaults include:

- large fonts
- high contrast
- oversized controls
- simplified language mode
- repeat last answer

---

## Emergency Handling

Medication Copilot is not an emergency-response application.

Requests involving overdose, poisoning, unconsciousness,
difficulty breathing, or other medical emergencies must
return the application's emergency escalation response.

The application must not:

- calculate emergency risk
- recommend medication
- recommend dosage changes
- provide treatment advice

The application may:

- recommend contacting emergency services
- recommend contacting poison control
- state that it cannot provide emergency medical advice

Emergency handling must remain deterministic.

---

## Current Project Status

Completed

✓ Phase 1
FHIR conversion and medication safety pipeline

✓ Phase 2
Runtime architecture and Gemma integration

✓ Phase 2.5
Repository cleanup and demo tooling

✓ Phase 3
Accessible React dashboard and FastAPI interface

Planned

Phase 4
Voice interaction

Phase 5
Vision / medication recognition

Phase 6
Android deployment

The medication runtime engine should now be considered stable.
Future work should primarily extend user interaction layers rather than modifying deterministic medication behavior.

---

## 24. Final Rule

When source data is missing, ambiguous, conflicting, or clinically uncertain:

> Preserve the uncertainty, require verification, and never guess.
