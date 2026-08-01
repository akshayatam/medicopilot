# Contributing

Read [rules.md](rules.md) completely before changing code or data. It is the authoritative safety and data specification.

## Environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For natural-language routing, install Ollama and run:

```bash
ollama pull gemma4:e2b
```

## Demo data and checks

Never hand-edit `data/runtime_patients/*.runtime.json` or the reconciliation profiles. Regenerate through the official pipeline:

```bash
python scripts/prepare_demo_data.py
# or the staged, validated workflow:
python app.py reset-demo
python app.py verify-demo
```

Before opening a pull request, run:

```bash
pytest -m "not integration"
python -m compileall -q app.py medication gemma ui scripts evaluation
git diff --check
```

Use `python app.py verify-demo --require-model` only when Ollama and the configured model are available.

## Code organization

- `medication/`: deterministic schemas, safety, conversion, reconciliation, repositories, and services
- `gemma/`: local model client and bounded intent-routing layer
- `scripts/`: conversion and demo lifecycle tools
- `ui/`: local Gradio interface
- `tests/`: non-live regression coverage

Preserve source-record, verified-plan, and adherence-ledger separation. Never let model output become medication fact, resolve ambiguity clinically, invent a schedule, bypass readiness, or weaken deterministic safety. New voice/image work belongs to future phases and must not bypass these boundaries.

## Pull-request checklist

- [ ] I read `rules.md` and preserved its safety boundaries.
- [ ] I did not manually edit generated runtime patients or protected profiles.
- [ ] I added or updated tests for behavioral changes.
- [ ] The non-live suite and compilation check pass.
- [ ] Demo reset and verification pass when relevant.
- [ ] Documentation distinguishes current functionality from future work.
- [ ] I did not include raw Synthea output, patient corpora, model artifacts, logs, caches, or secrets.

