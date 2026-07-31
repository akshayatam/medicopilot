You are working inside the root of an existing Python project called
`medicopilot`.

Your task is to turn the current deterministic medication-data demo into a
complete local AI-powered medication copilot using Gemma 4 through Ollama.

Important context:

- The application is for a healthcare hackathon focused on on-device AI.
- All AI inference and patient data processing must remain local.
- No cloud APIs, hosted LLMs, remote databases, analytics, telemetry, or external
  patient-data transmission may be used.
- The app must use synthetic data only.
- The app is a decision-support and medication-navigation tool.
- It must not diagnose, recommend treatment, modify dosages, suggest stopping
  medication, assess drug interactions, or make clinical decisions.
- Voice and image support are not required now, but the architecture must make
  them easy to add later.
- The current repository already contains deterministic medication logic. Reuse
  and extend it rather than replacing it unnecessarily.

Before making changes:

1. Inspect the entire repository.
2. Read:
   - `README.md`
   - `app.py`
   - `data/synthetic_patient.json`
   - all files under `medication/`
3. Explain briefly, in your work log, the existing architecture and what you will
   preserve.
4. Do not begin implementation until you understand how the current command-line
   operations work.

==================================================
PRIMARY GOAL
==================================================

Build a complete local text-based medication copilot with this flow:

User enters a natural-language request
        ↓
Gemma 4 runs locally through Ollama
        ↓
Gemma returns a structured intent
        ↓
Python validates the intent
        ↓
The application executes an approved deterministic medication function
        ↓
The tool result is returned to Gemma or formatted deterministically
        ↓
The user receives a grounded response based only on local synthetic records

The model must never be the source of truth for medication schedules, dose
history, dosage, or instructions. The local repository and medication service
must remain the factual source of truth.

==================================================
TECHNOLOGY REQUIREMENTS
==================================================

Use:

- Python 3.10+
- Ollama local HTTP API
- Gemma 4 E2B as the default model:
  `gemma4:e2b`
- Pydantic for validating model outputs
- Requests or httpx for calling Ollama
- Gradio for the initial web interface
- Pytest for tests
- Existing JSON data file as the initial persistence layer

Do not use:

- OpenAI API
- Gemini API
- Hugging Face hosted inference
- Firebase
- cloud databases
- Docker unless strictly needed
- LangChain unless there is a compelling technical reason
- large agent frameworks
- vector databases
- fine-tuning
- real patient data
- automatic medical advice

Prefer simple, explicit Python over excessive abstraction.

==================================================
RECOMMENDED PROJECT STRUCTURE
==================================================

Restructure or extend the repository toward this layout:

medication-copilot-starter/
├── README.md
├── requirements.txt
├── pyproject.toml or pytest.ini
├── app.py
├── config.py
│
├── data/
│   ├── synthetic_patient.json
│   └── evaluation_cases.jsonl
│
├── medication/
│   ├── __init__.py
│   ├── models.py
│   ├── repository.py
│   ├── service.py
│   ├── safety.py
│   └── schemas.py
│
├── gemma/
│   ├── __init__.py
│   ├── client.py
│   ├── prompts.py
│   ├── schemas.py
│   ├── intent_router.py
│   ├── response_parser.py
│   └── orchestrator.py
│
├── ui/
│   ├── __init__.py
│   └── gradio_app.py
│
├── evaluation/
│   ├── __init__.py
│   └── evaluate.py
│
└── tests/
    ├── test_repository.py
    ├── test_service.py
    ├── test_safety.py
    ├── test_intent_parser.py
    └── test_orchestrator.py

You may adjust filenames if needed, but preserve clear separation between:

1. local data and deterministic medication logic;
2. AI inference;
3. intent validation;
4. safety rules;
5. orchestration;
6. UI;
7. evaluation.

==================================================
SUPPORTED USER ACTIONS
==================================================

The AI must classify requests into exactly one of these actions:

1. LIST_TODAY_MEDICATIONS
2. CHECK_DOSE_STATUS
3. FIND_NEXT_DOSE
4. MARK_DOSE_TAKEN
5. GET_SAVED_INSTRUCTIONS
6. SHOW_MEDICATION_HISTORY
7. NEEDS_CLARIFICATION
8. UNSAFE_MEDICAL_REQUEST
9. OUT_OF_SCOPE

Define a strict enum for these actions.

The structured model output should follow a schema similar to:

{
  "action": "CHECK_DOSE_STATUS",
  "medication_reference": "blood pressure medicine",
  "date_reference": "today",
  "time_period": "morning",
  "confidence": 0.95,
  "clarification_question": null,
  "unsafe_reason": null
}

Fields may be null where not applicable.

Validate all model outputs with Pydantic.

If validation fails:

- do not execute any medication function;
- retry once with a repair prompt;
- if the repair also fails, return a safe error message.

Never use `eval()` or execute model-generated code.

==================================================
SAFETY RULES
==================================================

Create a deterministic safety layer that runs before any action execution.

The following requests must map to `UNSAFE_MEDICAL_REQUEST`:

- changing a dose;
- doubling a dose;
- skipping a prescribed dose;
- stopping a medication;
- replacing one medication with another;
- asking whether two medications can be combined;
- asking about medication interactions;
- asking what medicine to take for a symptom;
- asking whether a medicine is safe for a condition;
- asking for diagnosis;
- asking for treatment recommendations;
- asking the app to override saved prescription instructions;
- asking what to do after an overdose or accidental ingestion.

Safe response style:

“I can help you review your saved medication schedule and dose history, but I
cannot recommend changes to medication or provide treatment advice. Please
contact a clinician, pharmacist, or emergency service as appropriate.”

For suspected overdose, accidental ingestion, severe symptoms, or emergency
language, return a stronger escalation response. Do not attempt clinical triage
beyond a clear recommendation to contact emergency services or poison control.

The app may safely say:

- what is stored in the verified medication record;
- whether a dose was logged;
- when the next saved dose is scheduled;
- what the saved instructions say;
- which medication entry matches a user-provided name or purpose label;
- that a request is ambiguous and needs clarification.

The app must never infer missing prescription information.

==================================================
GEMMA / OLLAMA CLIENT
==================================================

Implement a reusable Ollama client.

Requirements:

- Default base URL:
  `http://localhost:11434`
- Default model:
  `gemma4:e2b`
- Read values from environment variables where appropriate:
  - `OLLAMA_BASE_URL`
  - `OLLAMA_MODEL`
  - `OLLAMA_TIMEOUT_SECONDS`
- Use a reasonable timeout.
- Handle:
  - Ollama not running;
  - model not installed;
  - timeout;
  - malformed response;
  - empty response;
  - non-JSON model output.
- Return user-friendly errors.

Use the Ollama chat API if it supports structured chat roles cleanly.
Otherwise use the generate API with a carefully formatted prompt.

Do not manually insert Gemma tokenizer control tokens unless necessary.
Prefer the runtime’s supported chat interface.

Create a health-check method that verifies:

- Ollama is reachable;
- the configured model is available;
- a minimal generation request succeeds.

Expose this check in both the CLI and Gradio UI.

==================================================
SYSTEM PROMPT
==================================================

Create a dedicated system prompt in `gemma/prompts.py`.

It should tell Gemma:

- it is an intent-routing component;
- it does not provide medical knowledge or advice;
- it may only choose from the allowed actions;
- it must return JSON only;
- it must not invent medication names, strengths, times, instructions, or logs;
- it must classify unsafe requests correctly;
- ambiguous requests must use `NEEDS_CLARIFICATION`;
- unsupported non-medication requests must use `OUT_OF_SCOPE`;
- no prose or markdown should appear outside the JSON object.

Keep the prompt readable and versioned in code.

Add a separate repair prompt for malformed output.

Do not enable extended thinking mode for the first implementation.
This task should prioritize low latency and structured reliability.

==================================================
INTENT ROUTER
==================================================

Implement an `IntentRouter` that:

1. receives normalized user text;
2. applies deterministic safety checks first;
3. sends the request to Gemma only when appropriate;
4. parses the model response;
5. validates it with Pydantic;
6. retries once if needed;
7. returns a typed intent object.

The deterministic safety layer should catch obvious high-risk phrases before the
LLM call.

Do not rely exclusively on keyword matching, but use it as an additional
guardrail.

==================================================
TOOL ORCHESTRATION
==================================================

Implement an orchestrator that maps validated actions to explicit Python
functions.

Example mapping:

LIST_TODAY_MEDICATIONS
    -> MedicationService.list_today_medications()

CHECK_DOSE_STATUS
    -> MedicationService.check_dose_status()

FIND_NEXT_DOSE
    -> MedicationService.find_next_dose()

MARK_DOSE_TAKEN
    -> MedicationService.mark_dose_taken()

GET_SAVED_INSTRUCTIONS
    -> MedicationService.get_saved_instructions()

SHOW_MEDICATION_HISTORY
    -> a new service method that returns recent dose logs

The orchestrator must:

- reject missing required fields;
- request clarification when medicine references are ambiguous;
- prevent duplicate dose logging;
- never execute unsupported actions;
- log only non-sensitive technical metadata;
- avoid storing full user prompts unless explicitly needed for local debugging.

For the final response, prefer deterministic templates using tool output.

Gemma may optionally rewrite the final answer for naturalness, but only if:

- the factual tool result is injected explicitly;
- the prompt says not to add facts;
- the system can fall back to deterministic formatting;
- tests confirm that no unsupported facts are added.

For the first implementation, deterministic final-response templates are
preferred.

==================================================
DATE AND TIME HANDLING
==================================================

Use the patient timezone from the local JSON file.

Support:

- today;
- this morning;
- this afternoon;
- this evening;
- tonight;
- explicit ISO dates;
- current local time.

Use Python `datetime` and `zoneinfo`.

Do not rely on the LLM to calculate timestamps.

Create a deterministic date/time resolver.

For demo reproducibility, allow an optional fixed current-time value via:

- CLI argument;
- environment variable such as `DEMO_NOW`;
- function injection in tests.

==================================================
MEDICATION MATCHING
==================================================

Support matching by:

- exact medication name;
- medication name plus strength;
- purpose label such as “blood pressure medicine”;
- case-insensitive partial match.

If multiple medicines match a reference:

- do not guess;
- return `NEEDS_CLARIFICATION`;
- show the possible matches.

If no medicine matches:

- state that it is not found in the local saved record;
- do not propose a medication.

==================================================
GRADIO USER INTERFACE
==================================================

Create a clean local Gradio interface.

The interface should contain:

1. Header
   - project name;
   - short privacy statement;
   - visible “Local only” indicator.

2. System status
   - Ollama reachable;
   - model loaded or available;
   - patient data loaded;
   - current configured model.

3. Today’s medications
   - name;
   - strength;
   - scheduled time;
   - purpose;
   - status;
   - taken time when applicable.

4. Ask the copilot
   - text input;
   - submit button;
   - example prompts;
   - response area.

5. Recent history
   - latest dose records.

6. Safety notice
   - not a diagnostic or treatment tool;
   - uses synthetic data;
   - instructions come only from the locally stored record.

7. Debug panel
   - optional and collapsed by default;
   - parsed intent;
   - selected action;
   - tool output;
   - model latency;
   - no hidden reasoning or chain-of-thought.

Do not display model internal reasoning.

The UI should function at:

`http://127.0.0.1:7860`

Do not enable public Gradio sharing.

==================================================
CLI SUPPORT
==================================================

Preserve the existing deterministic CLI commands.

Add:

1. AI query command:

   python app.py ask "Did I take my blood pressure medicine this morning?"

2. Ollama health check:

   python app.py health

3. Run the Gradio interface:

   python app.py serve

4. Optional fixed demo time:

   python app.py ask "What comes next?" \
     --now 2026-08-01T10:00:00+05:30

The existing commands such as `today`, `status`, `next`, `mark-taken`, and
`instructions` should continue to work.

==================================================
EVALUATION DATASET
==================================================

Create `data/evaluation_cases.jsonl` with at least 50 synthetic examples.

Include these categories:

- supported English requests;
- Hindi requests;
- Hinglish requests;
- ambiguous medication references;
- unsafe dosage-change requests;
- medication-interaction requests;
- requests unrelated to medication management;
- malformed or adversarial prompts;
- attempts to override the system prompt;
- duplicate “mark taken” requests.

Each row should contain:

{
  "id": "case_001",
  "input": "Did I take my BP tablet this morning?",
  "expected_action": "CHECK_DOSE_STATUS",
  "expected_safe": true,
  "notes": "Purpose-label reference"
}

Create an evaluation script that measures:

- action accuracy;
- unsafe-request recall;
- valid structured-output rate;
- clarification accuracy;
- hallucinated-medication rate;
- average model latency.

The evaluation script should save results to a timestamped JSON file.

Tests must not require a live Ollama instance unless explicitly marked as
integration tests.

==================================================
TESTING
==================================================

Add comprehensive tests.

Unit tests should cover:

- loading the synthetic JSON;
- medication lookup;
- ambiguous matches;
- listing today’s medications;
- checking dose status;
- finding next dose;
- marking a dose as taken;
- duplicate marking;
- saved instructions;
- time-period resolution;
- deterministic safety rules;
- valid intent parsing;
- invalid JSON;
- unsupported actions;
- repair behavior;
- model client failures;
- orchestrator action mapping.

Mock the Ollama API for normal unit tests.

Mark live model tests separately, for example:

`@pytest.mark.integration`

All non-integration tests should pass without Ollama running.

==================================================
FUTURE VOICE AND IMAGE EXTENSIBILITY
==================================================

Do not implement voice or image features now.

However, design the input model so future modalities can be added without
rewriting the orchestration layer.

Create an input abstraction similar to:

class UserInput:
    text: str | None
    source: Literal["text", "voice", "image"]
    transcript: str | None
    image_path: str | None
    metadata: dict

For now, only `source="text"` is active.

Document future extension points:

Voice:
audio file
    -> local Gemma audio transcription
    -> normalized text
    -> existing intent router

Image:
image file
    -> local Gemma image extraction
    -> verified structured data
    -> existing medication service

The existing intent router and medication tools should not care whether the text
originally came from typing, voice transcription, or image extraction.

Do not create empty overengineered modules. Add only the minimal interfaces and
documentation needed for future support.

==================================================
README
==================================================

Rewrite the README so it includes:

- project purpose;
- healthcare scope and safety boundaries;
- privacy architecture;
- current features;
- project structure;
- Python setup;
- Ollama installation expectations;
- model download command:
  `ollama pull gemma4:e2b`
- dependency installation;
- CLI examples;
- Gradio launch instructions;
- evaluation instructions;
- test instructions;
- demo script;
- troubleshooting;
- future voice/image roadmap;
- synthetic-data disclaimer.

Include a simple architecture diagram in Mermaid:

User text
    -> Safety layer
    -> Gemma intent router
    -> Pydantic validation
    -> Deterministic medication service
    -> Local JSON storage
    -> Grounded response

==================================================
REQUIREMENTS
==================================================

Create a minimal `requirements.txt`.

Likely dependencies:

- pydantic
- requests or httpx
- gradio
- pytest
- pytest-mock

Pin compatible version ranges where reasonable, but do not over-pin every
transitive dependency.

==================================================
IMPLEMENTATION ORDER
==================================================

Follow this order:

Phase 1:
- inspect and preserve existing behavior;
- add configuration;
- add Pydantic schemas;
- add safety rules;
- add tests.

Phase 2:
- add Ollama client;
- mock it in tests;
- add intent router;
- add output repair logic.

Phase 3:
- add orchestrator;
- connect allowed actions to medication service;
- add deterministic response formatting.

Phase 4:
- add CLI `ask` and `health`;
- preserve existing CLI commands.

Phase 5:
- add Gradio interface.

Phase 6:
- add evaluation dataset and evaluation runner.

Phase 7:
- update README;
- run tests;
- perform a final repository review.

Do not skip directly to UI implementation.

==================================================
ACCEPTANCE CRITERIA
==================================================

The project is complete only when all of the following work:

1. Existing deterministic commands still work.

2. With Ollama running and `gemma4:e2b` installed:

   python app.py ask \
     "Did I take my blood pressure medicine this morning?" \
     --now 2026-08-01T10:00:00+05:30

   returns a grounded answer based on the local dose log.

3. This request:

   python app.py ask \
     "I missed yesterday. Should I take two Metformin tablets today?"

   is refused as an unsafe medical request and does not execute any medication
   function.

4. This request:

   python app.py ask \
     "Mark my tablet as taken."

   asks for clarification instead of guessing.

5. This request:

   python app.py ask \
     "What comes next?" \
     --now 2026-08-01T10:00:00+05:30

   returns the next scheduled medication using deterministic local time logic.

6. `python app.py health` clearly reports whether Ollama and the configured model
   are available.

7. `python app.py serve` starts a local Gradio interface.

8. All unit tests pass without a live Ollama instance.

9. Integration tests are clearly separated.

10. No cloud service is required.

11. No model-generated medication fact is accepted without matching local data.

12. No voice or image functionality is implemented yet, but future integration
    points are clearly documented.

==================================================
FINAL WORK REPORT
==================================================

After implementation:

1. Run all non-integration tests.
2. Show the final test summary.
3. List all files created or changed.
4. Summarize the architecture.
5. Explain the safety controls.
6. Provide exact commands to:
   - install dependencies;
   - pull Gemma;
   - run health check;
   - ask a question;
   - launch Gradio;
   - run tests;
   - run evaluation.
7. Mention any limitations or anything that could not be verified locally.
8. Do not claim that Ollama integration works unless you actually tested it
   against a live local Ollama instance.
