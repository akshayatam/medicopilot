# Phase 2 — Runtime Integration

> Historical implementation brief. Phase 2 is complete; current capabilities and commands are documented in `README.md` and `docs/architecture.md`.

Read `rules.md` completely before making any changes. Treat it as the authoritative safety and data specification.

The repository currently has:

- A text-based Gradio application
- Gemma E2B running locally through Ollama
- Natural-language intent routing
- Deterministic medication functions
- A Synthea FHIR conversion pipeline
- Medication normalization
- Conflict detection
- Reconciliation
- Plan building
- Readiness assessment
- Seeded adherence simulation
- Pydantic validation
- Existing tests, currently reported as passing

Your task is to integrate the medication-safety pipeline with the existing Gemma and Gradio application so that the running copilot uses only reconciled, verified medication plans and app-generated dose logs.

Do not implement voice or image support yet. Preserve clean extension points for them.

Before coding:

1. Inspect the complete repository.
2. Read:
   - `rules.md`
   - `README.md`
   - `app.py`
   - all files under `medication/`
   - all files under `gemma/`
   - all files under `ui/`
   - all existing tests
3. Identify:
   - the current runtime patient-data format;
   - where Gradio loads patient data;
   - where Gemma receives patient context;
   - where medication services read medicines and dose logs;
   - whether global mutable state is used;
   - whether unreconciled source medications can currently reach the assistant.
4. Write a brief implementation plan before modifying files.
5. Preserve existing working CLI commands and tests unless they conflict with `rules.md`.

==================================================
PRIMARY OBJECTIVE
==================================================

Integrate these two existing systems:

System A:

Synthea FHIR
    -> conversion
    -> normalized source record
    -> reconciliation
    -> verified medication plan
    -> dose logs

System B:

Gradio text input
    -> Gemma E2B intent routing
    -> validated action
    -> deterministic medication service
    -> grounded response

The final runtime flow must be:

User text
    -> deterministic safety screening
    -> Gemma intent classification
    -> Pydantic validation
    -> patient readiness check
    -> deterministic medication resolution
    -> deterministic tool execution
    -> grounded response from verified local data

Gemma must never read unreconciled medication orders as though they are a current medication plan.

==================================================
RUNTIME DATA MODEL
==================================================

Create or formalize one canonical runtime patient schema.

It should conceptually contain:

{
  "schema_version": "2.0",
  "source_record": {
    "patient": {},
    "conditions": {},
    "allergies": [],
    "allergy_status": "not_recorded",
    "medications": [],
    "clinical_administrations": [],
    "provenance": {}
  },
  "medication_plan": {
    "patient_id": "...",
    "status": "verified",
    "medications": []
  },
  "dose_logs": [],
  "import_summary": {
    "ready_for_medication_tracking": true,
    "blocking_issues": [],
    "warnings": []
  }
}

You may adapt this to the existing schemas, but the following boundaries are mandatory:

- `source_record.medications` contains imported FHIR orders.
- `medication_plan.medications` contains only reconciled medication-plan entries.
- `dose_logs` contains only app-generated or explicitly simulated adherence events.
- The running assistant must not use source-record medications for daily medication answers.
- The source record remains available for review, provenance, and diagnostics.

Add schema-version validation and clear errors for unsupported versions.

==================================================
PATIENT DATA SERVICE
==================================================

Create a dedicated patient-loading layer rather than reading JSON directly in Gradio.

Add a class or equivalent abstraction such as:

class PatientDataService:
    def list_available_patients(...) -> list[PatientSummary]:
        ...

    def load_patient(patient_id: str) -> RuntimePatient:
        ...

    def get_readiness(patient_id: str) -> ReadinessResult:
        ...

    def reload_patient(patient_id: str) -> RuntimePatient:
        ...

Responsibilities:

- Discover available runtime patient files
- Validate files with Pydantic
- Reject unsupported schemas
- Expose patient summaries
- Enforce readiness
- Return user-friendly loading errors
- Avoid passing raw file dictionaries throughout the application

Do not place file-loading logic directly in Gradio callbacks.

==================================================
READINESS ENFORCEMENT
==================================================

Every medication-tracking operation must check:

`import_summary.ready_for_medication_tracking`

The following actions must not execute for an unready patient:

- LIST_TODAY_MEDICATIONS
- CHECK_DOSE_STATUS
- FIND_NEXT_DOSE
- MARK_DOSE_TAKEN
- SHOW_MEDICATION_HISTORY

Return a deterministic response such as:

“The medication plan has not been verified yet. Complete medication review before using reminders or dose tracking.”

The application may still show the patient in a review mode.

Gemma must not decide readiness.

Readiness must be determined by deterministic application logic.

==================================================
REPOSITORY BOUNDARIES
==================================================

Update the repository or data-access layer so the assistant uses only:

- confirmed current medicines;
- medicines included in the daily plan;
- verified reminder schedules;
- app or synthetic dose logs;
- allergy status;
- explicitly recorded aliases and user labels.

Add or formalize methods similar to:

get_confirmed_medications(patient_id)
get_verified_schedules(patient_id)
get_recent_dose_logs(patient_id)
get_allergy_status(patient_id)
get_source_medications_for_review(patient_id)

The first four support the patient-facing assistant.

`get_source_medications_for_review()` must be isolated to review/admin functionality.

Confirmed daily medicines must satisfy:

- `current_use_status == "confirmed_current"`
- `included_in_daily_plan == true`
- reconciliation status is verified

Do not silently include medicines merely because FHIR status is active.

==================================================
MEDICATION RESOLVER
==================================================

Implement a deterministic medication resolver.

It should resolve user references using:

- exact normalized name;
- patient-friendly name;
- name plus strength;
- aliases;
- user labels;
- explicit purpose labels;
- schedule labels such as “morning tablet,” where uniquely resolvable.

Return a typed result with exactly one of:

- MATCHED
- AMBIGUOUS
- NOT_FOUND

Example:

{
  "status": "AMBIGUOUS",
  "query": "heart tablet",
  "matches": [
    {
      "medication_id": "...",
      "display_name": "Metoprolol 100 mg"
    },
    {
      "medication_id": "...",
      "display_name": "Lisinopril 5 mg"
    }
  ]
}

Rules:

- Never ask Gemma to choose among ambiguous deterministic matches.
- Never match against excluded or unverified source medications.
- Never invent aliases.
- Do not use broad medical knowledge to infer a medicine’s purpose.
- A missing match must not result in a suggested medicine.

==================================================
GEMMA ROLE
==================================================

Keep Gemma E2B primarily as an intent router.

Gemma should receive:

- the user’s text;
- allowed actions;
- routing instructions;
- safety boundaries;
- minimal metadata needed for intent parsing.

Gemma should not receive:

- the full FHIR bundle;
- the complete source record;
- claims;
- full condition history;
- sensitive social conditions;
- the complete runtime patient JSON.

Preferred flow:

User text
    -> Gemma structured intent
    -> Pydantic validation
    -> deterministic medication resolver
    -> deterministic service operation
    -> deterministic final response

For the first integrated version, use deterministic response templates.

Do not use Gemma to rewrite grounded answers unless an optional, clearly separated mode already exists and can be proven not to add facts.

Do not expose chain-of-thought.

==================================================
SUPPORTED ACTION FLOW
==================================================

Ensure the existing action enum supports:

- LIST_TODAY_MEDICATIONS
- CHECK_DOSE_STATUS
- FIND_NEXT_DOSE
- MARK_DOSE_TAKEN
- GET_SAVED_INSTRUCTIONS
- SHOW_MEDICATION_HISTORY
- NEEDS_CLARIFICATION
- UNSAFE_MEDICAL_REQUEST
- OUT_OF_SCOPE

The orchestrator must:

1. Run deterministic safety checks.
2. Validate the patient selection.
3. Check readiness.
4. Resolve medication references deterministically.
5. Validate required fields.
6. Execute exactly one approved tool.
7. Return a grounded deterministic response.
8. Include debug metadata without hidden reasoning.

No tool may execute when:

- the intent is invalid;
- the patient is unready;
- the medicine is ambiguous;
- the medicine is not found;
- the request is unsafe;
- required fields are missing.

==================================================
FIXED DEMO CLOCK
==================================================

Add a clock abstraction.

Example:

class Clock:
    def now(self) -> datetime:
        ...

Implement:

- SystemClock
- FixedClock

Support a fixed demo time through an environment variable:

`DEMO_NOW=2026-08-01T10:00:00-04:00`

Optionally support a CLI argument where compatible.

All time-sensitive services must use the injected clock rather than calling `datetime.now()` directly.

This includes:

- today’s medicines;
- next dose;
- due/overdue logic;
- dose-log timestamps;
- history windows;
- Gradio status displays.

Validate timezone-aware timestamps.

==================================================
DOSE-LOG INTEGRATION
==================================================

Use the existing adherence ledger and guardrails.

Requirements:

- Dose logs reference only confirmed plan medications.
- Duplicate mark-taken operations are idempotent.
- An already-taken dose must not produce a second log.
- Ambiguous requests must not modify state.
- PRN medication must not appear as a recurring scheduled dose.
- `MedicationAdministration` must remain separate from home adherence logs.
- All updates must persist locally and safely.
- State-changing operations must be tested.

Use the strict statuses already defined in `rules.md`.

==================================================
GRADIO INTEGRATION
==================================================

Update the existing Gradio application with the following sections.

1. Header

Show:

- Application name
- “Runs locally” privacy statement
- Synthetic-data notice
- Non-diagnostic safety notice

2. Patient selector

Add a dropdown populated by `PatientDataService.list_available_patients()`.

Each option should show a concise label such as:

“Aaron Ritchie — 63 — Needs review”

Store the selected patient ID in `gr.State`.

Do not use one global mutable selected-patient variable.

3. Patient status panel

Show:

- Patient display name
- Age
- Preferred language
- Timezone
- Readiness status
- Confirmed medication count
- Allergy status
- Blocking issues
- Warnings

4. Today’s medications

Show only confirmed medicines from the verified plan.

Display:

- Friendly name
- Strength
- Scheduled time
- Status
- Taken time where applicable

If the patient is unready, show a clear review-required state rather than an empty schedule that could be misinterpreted.

5. Ask the copilot

Preserve the text interface.

Support example prompts such as:

- “What medicine comes next?”
- “Did I take my heart tablet this morning?”
- “Mark my evening medicine as taken.”
- “What are the saved instructions for Metoprolol?”

6. Recent history

Show recent app/synthetic dose logs only.

Do not mix clinical MedicationAdministration records into this list.

7. Review mode

Add a separate tab or section showing:

- imported source medications;
- FHIR status;
- current-use status;
- reconciliation flags;
- missing dosage warnings;
- old active orders;
- duplicate/conflict flags;
- whether each medicine is included in the plan.

A read-only review mode is sufficient.

Do not allow the patient-facing assistant to query these source records.

8. Debug panel

Add a collapsed debug panel showing:

- selected patient ID;
- readiness result;
- parsed intent;
- medication resolver result;
- selected tool;
- tool output;
- model latency;
- response source;
- errors or repair attempts.

Never show chain-of-thought.

9. System health

Show:

- Ollama reachable;
- configured Gemma model;
- model available;
- patient data directory readable;
- number of patients loaded;
- number ready;
- schema validation state.

The UI must still load when Ollama is unavailable. Show a clear local-model error instead of crashing.

Do not enable public Gradio sharing.

==================================================
SESSION AND STATE SAFETY
==================================================

Audit the current Gradio code for global mutable state.

Use session-specific state for:

- selected patient ID;
- conversation history;
- fixed demo time if configurable;
- debug output;
- pending clarification state.

Repository or service objects may be shared only if they are stateless or safely scoped.

Concurrent browser sessions must not accidentally share patient selection or conversation state.

Protect file writes against duplicate or conflicting updates where practical.

==================================================
CURATED DEMO DATA
==================================================

Create at least two runtime demo patients:

1. Ready patient

Must contain:

- At least three confirmed medicines
- Verified schedules
- At least one taken dose today
- At least one upcoming dose
- At least one missed or late historical dose
- One friendly alias such as “heart tablet”
- Allergy status represented accurately
- No unresolved blocking issues

2. Unready patient

Must contain:

- Imported source medicines
- No verified medication plan, or unresolved conflicts
- Readiness set to false
- Clear blocking issues

Optional third patient:

- One PRN medication
- No recurring reminder for the PRN medicine
- Multilingual preference stored for future voice work

Do not fabricate additions inside the source record.

Store synthetic reconciliation separately and build the runtime plan through the existing pipeline.

Use deterministic, clearly documented synthetic reconciliation profiles.

==================================================
CLI INTEGRATION
==================================================

Preserve existing CLI commands.

Ensure or add commands similar to:

python app.py list-patients

python app.py patient-status <patient_id>

python app.py ask \
  --patient <patient_id> \
  "What medicine comes next?"

python app.py serve

python app.py health

Support `DEMO_NOW`.

The CLI and Gradio application must use the same orchestration and repository layers. Do not duplicate business logic.

==================================================
END-TO-END TESTS
==================================================

Add integration tests for the complete application path.

Do not require live Ollama for standard tests. Mock the Gemma client.

Add at least these tests:

1. Ready patient, next dose

Input:
“What medicine comes next?”

Expected:

- Readiness passes
- Intent maps to FIND_NEXT_DOSE
- Verified schedule is queried
- Response contains only stored medication and time

2. Dose-status lookup

Input:
“Did I take my heart tablet this morning?”

Expected:

- Alias resolves deterministically
- One confirmed medication matches
- Dose log is queried
- Stored taken time is returned

3. Ambiguous medication

Input:
“Mark my tablet as taken.”

Expected:

- No state mutation
- Clarification response
- Candidate matches shown where useful

4. Unready patient

Input:
“What comes next?”

Expected:

- Tool execution blocked
- Verification-required response
- No source medication is treated as scheduled

5. PRN medicine

Input:
“When is my as-needed medicine due?”

Expected:

- No due time is invented
- Response states that it is saved as as-needed
- No recurring dose is generated

6. Unsafe medication request

Input:
“I missed yesterday. Should I take two today?”

Expected:

- Deterministic refusal
- No medication function executes
- No state mutation

7. Duplicate mark-taken

Execute the same valid mark-taken request twice.

Expected:

- Exactly one dose event
- Second result says it was already recorded

8. Ollama unavailable

Expected:

- Gradio and deterministic patient data still load
- Ask feature displays a local-model error
- Application does not crash

9. Sensitive context exclusion

Expected:

- Sensitive social conditions do not appear in Gemma context
- Source record is not sent to the model

10. Session isolation

Expected:

- Separate Gradio session-state objects do not share patient selection

==================================================
HEALTH CHECK
==================================================

Create one application health-check service that verifies:

- Ollama endpoint reachable
- Gemma E2B model available
- Runtime patient directory readable
- Patient files validate
- At least one ready demo patient exists
- Timezone data is valid
- Schema versions are supported

Return structured health output.

Use the same service in CLI and Gradio.

==================================================
README AND DOCUMENTATION
==================================================

Update the README with:

- Integrated architecture
- Data-layer boundaries
- Why raw FHIR orders are not daily plans
- Reconciliation workflow
- Runtime patient schema
- Gradio usage
- Patient selection
- Fixed demo clock
- CLI commands
- Health checks
- Test commands
- Demo walkthrough
- Privacy guarantees
- Safety limitations
- Future voice and image integration points

Add a Mermaid diagram:

Synthea FHIR
    -> Converter
    -> Source Record
    -> Reconciliation
    -> Verified Medication Plan
    -> Dose Ledger
    -> Deterministic Medication Service
    <- Validated Gemma Intent
    <- Gradio Text Input

Document that voice will later produce normalized text for the same intent router, and image extraction will require verification before modifying the medication plan.

==================================================
IMPLEMENTATION ORDER
==================================================

Follow this order:

Phase 1:
- Audit current architecture
- Formalize runtime schema
- Add patient-data service
- Add schema/readiness validation

Phase 2:
- Restrict repository access to verified plans
- Add deterministic medication resolver
- Add clock abstraction

Phase 3:
- Update orchestrator
- Add readiness blocking
- Connect dose-log state safely
- Add deterministic response templates

Phase 4:
- Add curated ready and unready demo profiles
- Build runtime patient files through existing reconciliation pipeline

Phase 5:
- Integrate patient selection and status into Gradio
- Add review mode
- Add debug and health panels
- Eliminate unsafe global state

Phase 6:
- Add CLI integration
- Add end-to-end tests
- Run complete test suite

Phase 7:
- Update README
- Perform final safety review

Do not begin with UI changes.

==================================================
ACCEPTANCE CRITERIA
==================================================

The implementation is complete only when:

1. Gradio loads multiple synthetic patients.
2. Patient selection is session-specific.
3. A ready patient can answer “What medicine comes next?” from a verified schedule.
4. A ready patient can answer “Did I take it?” only from dose logs.
5. Mark-taken updates local state without duplicates.
6. Ambiguous medication references never cause state mutation.
7. An unready patient cannot use reminder or adherence tools.
8. Raw source medications never enter daily assistant context.
9. PRN medication never receives an invented due time.
10. Frequency-only dosage never receives an invented clock time.
11. Allergy status `not_recorded` is never phrased as “no allergies.”
12. Sensitive social conditions are excluded from Gemma context.
13. Gemma is used for routing, not medication truth.
14. Deterministic services enforce all safety rules.
15. A fixed demo clock works.
16. Ollama failure does not crash the UI.
17. Standard tests do not require Ollama.
18. End-to-end mocked tests pass.
19. Existing guardrail tests continue to pass.
20. The README accurately describes the implemented system.

==================================================
FINAL REPORT
==================================================

After implementation:

1. Run the entire non-live test suite.
2. Run Python compilation checks.
3. Run CLI help and health checks.
4. Perform a smoke test using:
   - one ready patient;
   - one unready patient;
   - one safe query;
   - one ambiguous query;
   - one unsafe query.
5. List every changed file.
6. Summarize the architecture.
7. Explain how source records are isolated from verified plans.
8. Explain how readiness is enforced.
9. Explain how Gradio session state is handled.
10. Provide exact commands to:
    - prepare demo data;
    - run health checks;
    - launch Gradio;
    - ask through the CLI;
    - run tests.
11. State clearly whether live Gemma/Ollama integration was actually tested.
12. Report unresolved limitations honestly.

Most important invariant:

Removing Gemma should reduce natural-language convenience, but it must not change medication facts, schedules, readiness decisions, allergy meaning, safety behavior, or dose-history state.
