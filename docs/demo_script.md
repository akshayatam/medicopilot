# Five-minute demo script

## Before presenting

Start Ollama, then restore and verify the deterministic scenario:

```bash
export DEMO_NOW="2026-08-01T10:00:00-04:00"
python app.py reset-demo
python app.py verify-demo --require-model
cd frontend && npm install && npm run build && cd ..
python app.py serve
```

Open `http://127.0.0.1:7860` and select Elena Rivera, the ready patient.

## Walkthrough

### 0:00–0:40 — Problem and boundary

Explain that people managing several medicines may struggle to recall what comes next or whether a dose was recorded. State that this prototype uses synthetic data, runs inference locally, and navigates a verified plan; it does not make clinical decisions.

### 0:40–1:15 — Verified schedule

Point to Elena's ready status and today's three scheduled medicines. Emphasize that the schedule comes from explicit synthetic reconciliation, not from Gemma or an `active` FHIR order.

### 1:15–1:45 — Next dose

Prompt: **“What medicine comes next?”**

Expected: Vitamin D3 1000 IU at 1:00 PM, according to the saved plan.

### 1:45–2:15 — Dose status and alias

Prompt: **“Did I take my heart tablet this morning?”**

Expected: the resolver maps the saved alias to Metoprolol succinate ER; the ledger reports it taken at 8:11 AM.

Use the **Mark next dose taken** quick action to show the exact-dose confirmation dialog. Cancel it first to demonstrate that no state changes until confirmation.

### 2:15–2:50 — Ambiguity without mutation

Prompt: **“Mark my tablet as taken.”**

Expected: clarification listing multiple confirmed matches. No dose state changes. Mention that Gemma preserves “tablet,” while the deterministic resolver owns ambiguity.

### 2:50–3:20 — Safety refusal

Prompt: **“I missed yesterday. Should I take two today?”**

Expected: deterministic refusal directing the user to a clinician or pharmacist. The local model is bypassed and no tool mutates state.

### 3:20–4:05 — Unready patient

Switch to Marcus Chen. Point out the two conflicting unverified source orders.

Prompt: **“What medicine comes next?”**

Expected: medication tracking is blocked until review. Raw orders cannot drive reminders or next-dose answers.

### 4:05–5:00 — Architecture and close

Summarize the source-record → reconciliation → verified-plan boundary, deterministic safety before Gemma, Pydantic intent validation, and deterministic medication service. Mention voice and verified image/document ingestion only as future extensions.

## If Ollama is unavailable

1. Run `python app.py verify-demo` without `--require-model` and show that all data checks pass while model health is a warning.
2. Use `python app.py health`, patient selection, today's schedule, source review, and recent history to demonstrate deterministic local data.
3. Explain that natural-language routing requires Ollama, while safety/data validation and direct deterministic CLI commands remain available.
4. Do not imply that a live model response was shown.

## Points to emphasize

- Synthetic data and local inference only
- Human reconciliation establishes the usable plan
- Gemma routes language; deterministic code owns facts, matching, readiness, safety, and persistence
- Ambiguity and unready data cause safe non-mutation
- The demo clock makes the scenario reproducible

## Claims not to make

- Do not claim diagnosis, prescribing, treatment recommendations, interaction checking, or clinical validation.
- Do not call imported source orders a verified current medication list.
- Do not claim production reminders, voice, image scanning, hospital integration, mobile deployment, or real patient support.
- Do not claim “no allergies” when the file says allergy information is not recorded.
- Do not claim model availability unless strict live verification actually passed.
