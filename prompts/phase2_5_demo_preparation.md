# Phase 2.5 — Demo Preparation and Repository Cleanup

> Historical implementation brief. Phase 2.5 is complete; current capabilities and commands are documented in `README.md` and `docs/architecture.md`.

## Required reading

Before making any changes:

1. Read `rules.md` completely.
2. Read `README.md`.
3. Inspect the existing repository structure.
4. Inspect the current CLI, demo-data preparation script, health checks, tests,
   Gradio application, and configuration.
5. Write a brief implementation plan before modifying files.

Treat `rules.md` as the authoritative safety and data specification.

---

## Context

Phase 2 has been completed successfully.

Verified capabilities include:

- Stable runtime architecture
- Medication safety pipeline
- Schema-v2 runtime patients
- Gemma intent routing
- Deterministic safety screening
- Deterministic medication resolution
- Ready and unready patient workflows
- Fixed demo clock
- Live Ollama routing
- Grounded responses from verified plans and dose logs

The current test baseline is 64 passing non-live tests.

The backend is now feature-frozen.

This phase must not modify:

- Medication logic
- Medication reconciliation behavior
- Runtime schemas
- Intent-routing semantics
- Safety rules
- Readiness enforcement
- Allergy semantics
- Dose-log semantics
- Verified-plan boundaries
- Deterministic response facts

The purpose of this phase is to improve repository hygiene, reproducibility,
documentation, developer onboarding, and demo reliability.

Do not implement Phase 3 UI redesign, voice, image input, or new medication
features.

---

# Repository Cleanup Verification

The repository has already been manually cleaned.

The following generated directories were intentionally removed:

- `data/patients/`
- `data/synthea/output/`

Do not recreate these directories.

The current runtime demo does not depend on them.

Search the complete repository for references to:

- `data/patients`
- `data/synthea/output`
- obsolete converted-Synthea paths
- deleted representative filenames

If stale references remain, update the relevant documentation, scripts, tests, or
configuration without changing runtime behavior.

Do not remove the Synthea FHIR converter merely because raw generated FHIR data
is not currently stored in the repository. The converter remains a supported
project capability.

Add generated Synthea locations to `.gitignore` so they are not recommitted.

---

# Protected Files

The following files are required and must not be deleted or renamed:

```text
data/reconciliation/ready_demo.json
data/reconciliation/unready_demo.json

data/runtime_patients/ready.runtime.json
data/runtime_patients/unready.runtime.json

data/evaluation_cases.jsonl
data/synthetic_patient.json

rules.md
```

Rules:

1. Reconciliation profiles must not be manually rewritten.
2. Runtime patient files must not be hand-edited.
3. Runtime patients may only be regenerated through the official demo-data
   preparation pipeline.
4. Do not change demo patient IDs, aliases, medication schedules, readiness
   state, dose history, or fixed-clock assumptions.
5. `data/evaluation_cases.jsonl` must remain available to the evaluation runner.
6. `data/synthetic_patient.json` must remain because legacy configuration and
   tests still reference it.
7. If any protected file appears obsolete, report it instead of removing it.

The official regeneration command is:

```bash
python scripts/prepare_demo_data.py
```

---

# Goals

Improve:

- Repository quality
- Demo reliability
- Documentation
- Developer onboarding
- Reproducibility
- GitHub presentation
- Safe reset and verification workflows

Do not add medication functionality.

---

# Task 1 — Repository Hygiene

Audit the repository for:

- Python caches
- Test caches
- Coverage output
- Virtual environments
- Editor metadata
- Logs
- Temporary files
- Runtime backup directories
- Temporary generated files
- Large model artifacts
- Raw generated Synthea output
- Obsolete archived prompts or duplicate rule files

Update `.gitignore` appropriately.

Do not delete tracked runtime patients, reconciliation profiles, evaluation data,
legacy test data, converter code, or files required by tests.

If `oldrules.md` or another obsolete rules file exists:

1. Confirm that nothing references it.
2. Remove it or move it to a clearly labelled archive.
3. Ensure `rules.md` remains the only authoritative rules document.

Do not broadly delete files merely because they appear generated or old.

---

# Task 2 — Demo Reset Command

Implement:

```bash
python app.py reset-demo
```

The command must:

1. Generate fresh demo data into a temporary location.
2. Validate all generated runtime patients with the existing Pydantic schemas.
3. Verify that the expected ready and unready patients are present.
4. Atomically replace the existing runtime files only after validation succeeds.
5. Restore the deterministic demo state.
6. Print a concise completion report.

Requirements:

- Idempotent
- Safe to run repeatedly
- Same inputs produce equivalent runtime data
- No partially deleted runtime state if generation fails
- No manual edits required
- Uses the existing preparation pipeline rather than duplicating medication
  logic

Do not implement reset by deleting valid files before replacements have been
successfully generated and validated.

---

# Task 3 — Demo Verification Command

Implement:

```bash
python app.py verify-demo
```

Return a concise structured or human-readable report.

## Required checks

These checks must determine whether the local demo data is valid:

- Runtime patient directory exists
- Expected runtime patient files exist
- Runtime schemas validate
- Patient IDs are valid and unique
- At least one ready patient exists
- At least one unready patient exists
- Reconciliation profiles exist and validate
- Ready patient contains confirmed plan medications
- Ready patient contains verified schedules
- Dose logs reference valid plan medications
- Unready patient remains blocked
- Timezones validate
- Active demo clock is displayed
- Protected files exist

A failure in these checks should make verification fail.

## Live-model checks

Also report:

- Ollama configured endpoint
- Ollama reachable
- Configured Gemma model
- Model available
- Minimal generation succeeds

Ollama unavailability should be reported clearly as a warning unless a
`--require-model` option is supplied.

Support:

```bash
python app.py verify-demo --require-model
```

With `--require-model`, Ollama and model failures should make verification fail.

This lets repository and data validation work even when Ollama is temporarily
stopped.

---

# Task 4 — Improve README

Rewrite or improve the README professionally without overstating implemented
features.

Include:

## Project overview

Explain Medication Copilot as a privacy-first, local medication-navigation and
adherence-support prototype for older adults and caregivers.

State clearly that it does not diagnose, prescribe, recommend treatment, or
change dosages.

## Motivation

Explain the difficulty older adults may face when managing several medicines
and remembering whether a scheduled dose was taken.

## Architecture

Include a Mermaid diagram representing:

```text
Synthetic patient source / Synthea FHIR
    → Conversion
    → Unverified source record
    → Reconciliation
    → Verified medication plan
    → Runtime patient
    → Gradio text input
    → Deterministic safety screening
    → Gemma 4 intent routing
    → Pydantic validation
    → Deterministic medication service
    → Grounded local response
```

Clarify that the live demo currently uses curated synthetic runtime data for
repeatability.

Explain that Synthea ingestion remains supported, but raw converted records are
not trusted as daily plans until reconciled.

## Current features

Only describe implemented functionality, including:

- Local Gemma intent routing
- Verified medication plans
- Today’s schedule
- Next-dose lookup
- Dose-status lookup
- Mark-taken workflow
- Medication history
- Ready/unready enforcement
- Deterministic safety refusals
- Synthetic demo patients
- Local Gradio interface
- Health and debug information

Do not claim production reminders, voice, image scanning, hospital integration,
or mobile deployment are implemented.

## Setup

Include:

- Supported Python version
- Virtual-environment creation
- Dependency installation
- Ollama expectations
- Gemma model pull command
- Demo reset
- Demo verification
- Gradio launch
- Test commands

## Demo

Document this sequence:

```bash
python app.py reset-demo
python app.py verify-demo
python app.py serve
```

## Screenshots

Add clearly marked placeholders if screenshots are not yet available.

## Safety and privacy

Explain:

- Synthetic data only
- No cloud LLM
- Patient-facing actions use only verified plans
- Raw FHIR orders remain isolated
- Gemma routes language but is not the medication source of truth

## Future work

Clearly label these as future work:

- Voice
- Image/document input
- Native Android deployment
- Healthcare-system integration

---

# Task 5 — Architecture Documentation

Create:

```text
docs/architecture.md
```

Include:

- System overview
- Repository structure
- Runtime request flow
- Source-record versus verified-plan separation
- Readiness enforcement
- Medication resolver behavior
- Deterministic safety boundaries
- Gemma responsibilities and non-responsibilities
- Persistence flow
- Fixed clock
- Demo-data generation
- Health checks
- Future voice and image insertion points

This document must reflect the implemented architecture rather than an imagined
future architecture.

---

# Task 6 — Project Roadmap

Create:

```text
docs/roadmap.md
```

Include:

## Completed

- Phase 1 — Data pipeline and initial medication services
- Phase 2 — Runtime integration, safety enforcement, Gemma routing, and Gradio

## Current

- Phase 2.5 — Repository hygiene, documentation, and demo reliability

## Planned

- Phase 3 — UI and accessibility polish
- Phase 4 — Voice input/output
- Phase 5 — Image and prescription verification
- Post-hackathon native deployment work

Include a simple milestone map such as:

- `v0.1.0` — Local text prototype
- `v0.2.0` — Verified runtime integration
- `v0.3.0` — Demo-ready interface
- `v1.0.0` — Hackathon submission

Do not mark future features as complete.

---

# Task 7 — Demo Script

Create:

```text
docs/demo_script.md
```

Design a live walkthrough of approximately five minutes.

Suggested flow:

1. Introduce the observed medication-management problem.
2. Explain that all data and inference remain local.
3. Open the ready patient.
4. Show today’s verified schedule.
5. Ask: “What medicine comes next?”
6. Ask: “Did I take my heart tablet this morning?”
7. Demonstrate an ambiguous request without state mutation.
8. Demonstrate an unsafe dose-change request and deterministic refusal.
9. Switch to the unready patient.
10. Show that raw medication orders cannot drive reminders before review.
11. Briefly explain the architecture.
12. Mention voice and image support as future extensions.

Include:

- Exact demo prompts
- Expected results
- Reset command before presenting
- Fallback steps if Ollama is unavailable
- Points to emphasize to judges
- Claims that must not be made

---

# Task 8 — Contributing Guide

Create:

```text
CONTRIBUTING.md
```

Include:

- Environment setup
- Dependency installation
- Ollama setup
- Demo-data regeneration
- Test commands
- Compilation check
- Code organization
- Safety boundaries
- Requirement to read `rules.md`
- Prohibition against manually editing generated runtime patients
- Pull-request checklist

Keep it concise and project-specific.

---

# Task 9 — Repository Structure and Dead-Code Audit

Ensure the repository remains organized around:

```text
app.py
config.py
data/
docs/
evaluation/
gemma/
medication/
scripts/
tests/
ui/
README.md
CONTRIBUTING.md
rules.md
```

Audit unused files, imports, and obsolete comments.

Do not remove code solely because it is not used by the curated demo if it
supports documented conversion, evaluation, testing, or compatibility paths.

Before deleting code:

1. Search for imports and references.
2. Run tests.
3. Explain the reason in the final report.

Prefer reporting uncertain dead code rather than deleting it.

---

# Task 10 — Docstrings

Improve docstrings only where useful.

Public classes and functions should explain:

- Purpose
- Important parameters
- Return value
- Safety-relevant behavior where applicable

Avoid rewriting every internal helper or adding obvious comments.

Do not change function behavior while adding documentation.

---

# Task 11 — Demo Stability

The following sequence must consistently produce a usable demo:

```bash
python app.py reset-demo
python app.py verify-demo
python app.py serve
```

No manual JSON editing should be required.

Also verify:

```bash
DEMO_NOW="2026-08-01T10:00:00-04:00" python app.py verify-demo
```

The reset and verification commands must use the existing configuration and
runtime schemas.

---

# Verification Requirements

Run:

```bash
pytest -m "not integration"
python -m compileall -q app.py medication gemma ui scripts evaluation
python app.py reset-demo
python app.py verify-demo
git diff --check
```

When Ollama is available, also run:

```bash
python app.py verify-demo --require-model
```

Perform smoke tests for:

- Ready next-dose request
- Ready dose-status request
- Ambiguous medication request
- Unsafe dose-change request
- Unready patient request

---

# Acceptance Criteria

The work is complete only when:

1. Deleted Synthea directories are not recreated.
2. No stale references remain to deleted data paths.
3. Protected files remain present.
4. Runtime demo patients regenerate through the official pipeline.
5. Reset is atomic and idempotent.
6. Verification works without Ollama and clearly warns about model availability.
7. Strict verification can require Ollama.
8. Existing safety and runtime behavior remain unchanged.
9. No runtime schema changes are made.
10. No medication logic changes are made.
11. No reconciliation behavior changes are made.
12. No intent-routing semantics are changed.
13. All existing tests pass.
14. New reset and verification tests pass.
15. README accurately distinguishes implemented features from future work.
16. Architecture and demo documentation match the actual codebase.
17. The project is ready for Phase 3 without implementing Phase 3 itself.

---

# Final Report

After implementation, report:

- Implementation plan followed
- Files created
- Files changed
- Files removed or archived
- `.gitignore` changes
- Stale references corrected
- Reset command behavior
- Verification command behavior
- Documentation added
- Test totals
- Compilation result
- Demo smoke-test results
- Whether live Ollama verification succeeded
- Any uncertain or intentionally retained legacy files
- Any known limitations

Do not claim that live Ollama verification succeeded unless it was actually run.

Do not begin Phase 3.
