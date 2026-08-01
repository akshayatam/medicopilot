# Phase 4.2 — Time-Aware Dose Status and Conversational Follow-Up

## Required Reading

Before modifying code, read:

1. `rules.md`
2. `README.md`
3. `docs/architecture.md`
4. `prompts/phase4_2_overdue_and_followup.md`
5. `medication/runtime.py`
6. `medication/runtime_service.py`
7. `medication/runtime_repository.py`
8. `medication/clock.py`
9. `gemma/schemas.py`
10. `gemma/intent_router.py`
11. `gemma/orchestrator.py`
12. `ui/gradio_app.py`
13. `voice/`
14. all relevant tests

Treat `rules.md` as authoritative.

Write a concise implementation plan before changing files.

---

# Context

The application currently stores scheduled dose instances with statuses such as:

- `upcoming`
- `due`
- `taken`
- `taken_late`
- `missed`
- `skipped_by_user`
- `unknown`

A live issue has been observed:

- Vitamin D3 is scheduled for 1:00 PM.
- The current application time is after 1:00 PM.
- Next-dose lookup correctly skips it and returns the later Metformin dose.
- The dashboard and chat still display Vitamin D3 as `upcoming`.

This means different application surfaces are interpreting dose status differently.

A second issue has been observed:

When the user asks:

> Have I missed any medicine?

the application lists the schedule but does not identify unrecorded past doses or
offer a safe follow-up action.

---

# Primary Objectives

1. Introduce one canonical, time-aware dose-status calculation.
2. Ensure every application surface uses the same effective status.
3. Add a dedicated missed/overdue-dose query.
4. Add safe conversational follow-up for recording a uniquely identified dose as
   taken.
5. Preserve all existing safety, readiness, confirmation, and persistence rules.

---

# Core Safety Language

The application must distinguish between:

```text
No dose log exists
```

and:

```text
The patient definitely did not take the medicine
```

The application only knows what has been recorded.

Prefer:

> Vitamin D3 scheduled for 1:00 PM is not recorded as taken.

Avoid:

> You did not take Vitamin D3.

Prefer:

> Did you take it? I can record that dose as taken.

Avoid:

> You missed it, so take it now.

The app must not recommend whether the medicine should now be taken.

---

# Canonical Effective Status

Create one deterministic status function or service used everywhere.

Suggested interface:

```python
def calculate_effective_dose_status(
    dose: DoseLog,
    now: datetime,
    policy: DoseStatusPolicy,
) -> DoseStatus:
    ...
```

Do not duplicate time comparisons in:

- Gradio
- response templates
- repository code
- next-dose lookup
- history logic
- progress calculation
- voice code

All surfaces must use the same function.

---

# Status Policy

Introduce a configurable non-clinical timing policy.

Suggested model:

```python
class DoseStatusPolicy(BaseModel):
    due_window_minutes: int = 15
    overdue_grace_minutes: int = 30
```

Suggested behavior:

## Before scheduled time

```text
effective_status = upcoming
```

## From scheduled time until due-window end

```text
effective_status = due
```

## After the configured grace period with no taken record

```text
effective_status = missed
```

## Recorded taken before or near the scheduled time

```text
effective_status = taken
```

## Recorded taken after the configured lateness threshold

```text
effective_status = taken_late
```

Existing explicit statuses such as:

- `skipped_by_user`
- `unknown`

must retain their meaning.

The policy is an application-display and adherence-record policy, not a clinical
judgment.

Do not infer treatment consequences from `missed`.

---

# Stored Status Versus Effective Status

Avoid relying on stale persisted `"upcoming"` values after time passes.

Prefer preserving the scheduled dose record and deriving:

```json
{
  "stored_status": "upcoming",
  "effective_status": "missed"
}
```

at query time.

If the existing schema does not expose both fields, return effective status in
service result models without forcing a runtime schema migration.

Do not rewrite every future dose log merely because the clock changed.

A persisted mutation should occur only for actual user/app events, such as:

- taken
- taken_late
- skipped_by_user

Time-derived status should normally remain deterministic and computed from:

- `scheduled_at`
- `taken_at`
- current injected clock
- configured policy

---

# Single Source of Truth

The following must all use effective status:

- Dashboard medicine rows
- Next-medicine card
- Progress summary
- Today’s medicine list
- Missed-dose query
- Recent history
- Quick actions
- Text responses
- Voice responses
- Debug output

At the same `now`, these surfaces must never disagree.

Example at 1:58 PM:

```text
Metoprolol — taken
Vitamin D3 — missed / not recorded
Metformin — upcoming
```

Next medicine:

```text
Metformin at 8:00 PM
```

Progress:

```text
1 of 3 recorded as taken
1 not recorded after its scheduled time
1 remaining
```

---

# Progress Semantics

Progress must count:

Completed:

- `taken`
- `taken_late`

Not completed:

- `due`
- `missed`
- `upcoming`
- `skipped_by_user`
- `unknown`

PRN medicines must not appear in the recurring-dose denominator.

The UI must display text in addition to the bar.

Suggested text:

```text
1 of 3 scheduled doses recorded as taken
1 missed or overdue
1 remaining
```

Do not call this a clinical adherence score.

---

# New Intent: Missed-Dose Query

Add a dedicated action if one does not already exist:

```text
CHECK_MISSED_DOSES
```

Support phrases such as:

- “Have I missed any medicine?”
- “Did I miss a dose?”
- “What medicine have I not taken?”
- “Is anything overdue?”
- “Did I forget any tablet?”
- “What did I miss today?”

Gemma should only classify the request.

Deterministic code must identify effective missed doses.

Do not ask Gemma to calculate time status.

---

# Missed-Dose Service Result

Create a typed result.

Example:

```json
{
  "status": "missed_doses_found",
  "date": "2026-08-01",
  "doses": [
    {
      "medication_id": "med_vitamin_d",
      "name": "Vitamin D3",
      "strength": "1000 IU",
      "scheduled_at": "2026-08-01T13:00:00-04:00",
      "effective_status": "missed",
      "recorded_taken": false
    }
  ]
}
```

Possible outcomes:

- `no_missed_doses`
- `missed_doses_found`
- `patient_not_ready`
- `no_schedule_data`

---

# Response Behavior

## No missed doses

Use:

> Your local dose log does not show any missed scheduled doses today.

Do not claim perfect adherence beyond the stored record.

## Exactly one missed dose

Use:

> Vitamin D3 1000 IU was scheduled for 1:00 PM and is not recorded as taken. Did
> you take it? I can record that dose as taken.

This response may create a session-bound pending follow-up.

## Multiple missed doses

Use:

> I found 2 scheduled doses that are not recorded as taken:
>
> - Vitamin D3 1000 IU — 1:00 PM
> - Metformin 500 mg — 8:00 PM
>
> Which medicine would you like to review?

Do not offer one blanket “yes” action for multiple doses.

## Unready patient

Use the existing readiness block.

Do not query raw source orders.

---

# Conversational Follow-Up

When exactly one missed dose is identified, create a pending follow-up action in
session state.

Suggested structure:

```json
{
  "type": "record_missed_dose_as_taken",
  "patient_id": "demo-ready-001",
  "medication_id": "med_vitamin_d",
  "scheduled_at": "2026-08-01T13:00:00-04:00",
  "created_at": "2026-08-01T13:58:00-04:00",
  "expires_at": "2026-08-01T14:03:00-04:00",
  "prompt": "Did you take Vitamin D3 1000 IU scheduled for 1:00 PM?"
}
```

The pending action must be:

- session-specific;
- patient-specific;
- dose-specific;
- time-limited;
- visible to the user;
- revalidated before mutation.

---

# Yes/No Handling

Support contextual replies such as:

Affirmative:

- yes
- yeah
- yep
- I did
- yes, I took it
- correct

Negative:

- no
- nope
- I did not
- not yet

Cancel:

- cancel
- never mind
- stop

These replies may be handled deterministically when a valid pending action
exists.

Do not send a bare “yes” through ordinary medication inference when no pending
action exists.

## Affirmative response

When there is one valid pending dose and the preceding prompt clearly states the
exact medicine, strength, date, time, and action, an affirmative response may
serve as explicit confirmation.

Before mutation:

1. Verify patient ID still matches.
2. Verify pending action has not expired.
3. Reload patient data.
4. Verify readiness.
5. Verify medication remains confirmed.
6. Verify exact scheduled dose exists.
7. Verify it is not already recorded as taken.
8. Verify no ambiguity exists.
9. Execute through the existing runtime service.
10. Reload persisted state.

Response:

> Vitamin D3 1000 IU scheduled for 1:00 PM has been recorded as taken.

If it was already recorded:

> That dose was already recorded as taken.

## Negative response

Do not mutate.

Response:

> Okay. I did not change the dose record.

Do not recommend taking or skipping the medication.

## No pending action

For a bare response such as “yes” with no valid pending action:

> I’m not sure what you are confirming. Please tell me which medicine or action
> you mean.

No mutation.

---

# Pending-State Invalidation

Clear pending follow-up when:

- Patient changes
- User cancels
- Action succeeds
- Action fails validation
- Pending state expires
- A new unrelated request begins
- Demo data is reset
- Browser session ends

Do not store this state globally.

Do not write it into runtime patient JSON.

---

# Text and Voice Parity

The same behavior must work for:

- Typed questions
- Approved voice transcripts

Examples:

```text
Have I missed any medicine?
```

and a voice transcript containing the same text must produce equivalent results.

For voice:

- transcript review remains required;
- approved transcript enters the same orchestrator;
- follow-up confirmation remains session-specific;
- raw audio is not retained;
- “yes” from voice must pass through transcript review before mutation unless the
  existing approved-confirmation flow explicitly supports it safely.

Do not create a separate voice-only missed-dose implementation.

---

# Dashboard Requirements

At the current injected time:

- Future doses show `Upcoming`.
- Doses within the due window show `Due`.
- Past unrecorded doses after grace show `Missed` or `Not recorded`.
- Taken doses show `Taken`.
- Late taken doses show `Taken late`.

The dashboard must update when:

- time-dependent data is refreshed;
- a dose is recorded;
- the patient changes;
- demo data is reset.

Add a refresh action that recomputes effective statuses using the injected clock.

Do not cache stale status labels.

---

# UI Wording

Prefer:

```text
Missed / not recorded
```

or:

```text
Not recorded after scheduled time
```

when space allows.

A badge may say:

```text
Missed
```

but supporting text should clarify:

> No taken record exists for this scheduled dose.

Do not imply the system directly observed ingestion.

---

# Next-Dose Behavior

`find_next_dose()` must:

- exclude taken doses;
- exclude taken-late doses;
- exclude missed past doses;
- exclude skipped doses;
- return only future or currently due scheduled doses;
- clearly return no remaining dose when appropriate.

It must use the same effective-status service as the dashboard.

---

# History Behavior

Recent history should include:

- taken
- taken_late
- missed past doses
- skipped_by_user
- unknown past events

It should exclude future upcoming doses.

Use the same effective-status computation.

---

# Configuration

Expose timing policy through configuration.

Example environment variables:

```text
DOSE_DUE_WINDOW_MINUTES=15
DOSE_MISSED_AFTER_MINUTES=30
```

Requirements:

- Validate non-negative values.
- Use safe defaults.
- Include active policy in debug/health output.
- Do not allow UI users to change these values during the demo unless explicitly
  required.
- Document that these are application policy settings, not clinical guidance.

---

# Debug Output

Include:

```json
{
  "active_clock": "2026-08-01T13:58:00-04:00",
  "dose_status_policy": {
    "due_window_minutes": 15,
    "missed_after_minutes": 30
  },
  "stored_status": "upcoming",
  "effective_status": "missed",
  "scheduled_at": "2026-08-01T13:00:00-04:00"
}
```

Do not expose chain-of-thought.

---

# Safety Requirements

The application must not answer:

> Should I take the missed dose now?

with treatment advice.

Use the existing refusal:

> I can show that the dose is not recorded, but I cannot recommend whether to
> take it now or change the schedule. Please contact a clinician or pharmacist.

The missed-dose feature must not:

- recommend doubling;
- recommend skipping;
- recommend taking late;
- modify future schedules;
- infer clinical risk;
- mark multiple doses from one vague confirmation.

---

# Tests

Add tests for:

## Effective status

- Before scheduled time → upcoming
- At scheduled time → due
- Inside due window → due
- After missed threshold without taken record → missed
- Taken record remains taken
- Late taken record remains taken_late
- Skipped remains skipped_by_user
- Timezone-aware comparisons
- Naive timestamps rejected
- Injected fixed clock controls results

## Cross-surface consistency

At the same clock:

- dashboard status;
- today list;
- next-dose lookup;
- missed-dose query;
- history;
- progress

must agree.

## Query behavior

- “Have I missed any medicine?” routes to `CHECK_MISSED_DOSES`
- No missed doses
- Exactly one missed dose
- Multiple missed doses
- Unready patient blocked
- No raw source medications used

## Follow-up

- One missed dose creates pending state
- “yes” confirms exact pending dose
- “yeah” confirms exact pending dose
- “no” cancels without mutation
- “cancel” clears state
- Bare “yes” without pending state does not mutate
- Expired pending state does not mutate
- Patient switch invalidates pending state
- Dose already taken remains idempotent
- Multiple missed doses cannot be confirmed with one generic yes
- Unrelated request clears or suspends pending state safely

## Voice parity

- Approved voice transcript follows same missed-dose path
- Voice affirmative confirmation follows transcript-review rules
- Voice ambiguity does not mutate
- No audio or transcript is stored in patient JSON

## Regression

- Existing next-dose behavior
- Existing mark-taken workflow
- Existing safety refusals
- Existing readiness blocks
- Existing dashboard progress
- Existing voice workflow
- Existing reset and verification commands

---

# Demo Data

Do not manually edit runtime JSON.

Use the official demo-generation pipeline.

Ensure the generated dose instances support testing:

```text
8:00 AM — taken
1:00 PM — initially upcoming
8:00 PM — upcoming
```

At an injected clock after the configured missed threshold:

```text
1:00 PM dose → effective missed
```

Changing the clock must change effective status without requiring manual JSON
editing.

Reset-demo must restore deterministic baseline data.

---

# Documentation

Update:

- `README.md`
- `docs/architecture.md`
- `docs/demo_script.md`
- `docs/roadmap.md`
- `CONTRIBUTING.md`
- `rules.md` only when necessary and consistent with permanent policy

Document:

- Stored versus effective dose status
- Due window
- Missed threshold
- “Not recorded” wording
- Conversational confirmation
- Pending-state expiry
- Text/voice parity
- No treatment recommendation
- Configuration variables

---

# Acceptance Criteria

Phase 4.2 is complete only when:

1. Past unrecorded doses no longer display as upcoming.
2. Dashboard and chat use one canonical effective-status function.
3. Next-dose and dashboard results cannot disagree.
4. “Have I missed any medicine?” has a dedicated deterministic flow.
5. Responses say “not recorded” rather than claiming observed non-adherence.
6. Exactly one missed dose may produce a specific follow-up prompt.
7. A contextual affirmative reply can record only the exact pending dose.
8. Bare “yes” without pending state never mutates.
9. Multiple missed doses require explicit selection.
10. Pending state is session-specific, expiring, and patient-specific.
11. The mutation uses the existing runtime service.
12. Unready patients remain blocked.
13. Unsafe requests remain refused.
14. Voice and text use the same logic.
15. Progress updates after confirmed mutation.
16. Future doses remain upcoming.
17. Existing schemas remain backward compatible.
18. All prior tests continue to pass.

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

Test with:

```bash
DEMO_NOW="2026-08-01T12:45:00-04:00" python app.py serve
```

Expected:

- Vitamin D3 upcoming.

Then:

```bash
DEMO_NOW="2026-08-01T13:10:00-04:00" python app.py serve
```

Expected according to configured due window:

- Vitamin D3 due.

Then:

```bash
DEMO_NOW="2026-08-01T13:58:00-04:00" python app.py serve
```

Expected:

- Vitamin D3 missed/not recorded.
- Metformin is next.
- Progress is still 1 of 3 completed.

Ask:

```text
Have I missed any medicine?
```

Expected:

> Vitamin D3 1000 IU was scheduled for 1:00 PM and is not recorded as taken. Did
> you take it? I can record that dose as taken.

Reply:

```text
yes
```

Expected:

- exact Vitamin D3 dose recorded once;
- dashboard becomes 2 of 3;
- pending state clears;
- Metformin remains next.

After testing:

```bash
python app.py reset-demo
python app.py verify-demo
```

---

# Final Report

Report:

- Root cause of stale upcoming status
- Canonical status implementation
- Timing-policy defaults
- New intent/action
- Follow-up confirmation design
- Session-state behavior
- Dashboard changes
- Voice parity
- Files changed
- Tests added
- Total tests
- Manual clock tests
- Mutation tests
- Known limitations

Do not begin Phase 5.
