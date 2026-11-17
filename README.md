# TriageAssist

An AI incident triage assistant that analyzes logs, metrics, and deployments
to suggest evidence-linked root causes and diagnostic next steps.

Submit incident evidence as JSON; get a structured hypothesis, evidence
references, recommended diagnostic steps, uncertainties, and the evidence
actually used. No frontend required.

## Run

Requires [uv](https://docs.astral.sh/uv/) and
[Ollama](https://docs.ollama.com/). Run these commands from this directory:

```sh
uv sync --locked
ollama pull qwen2.5:7b
ollama serve
```

If Ollama is already running, skip `ollama serve`. In a second terminal:

```sh
uv run uvicorn app:app --host 127.0.0.1 --port 8765
```

Already have a model installed? Skip the pull and select it when starting the
API, for example:

```sh
OLLAMA_MODEL=gemma4:latest uv run uvicorn app:app --host 127.0.0.1 --port 8765
```

Submit the synthetic sample from another terminal:

```sh
curl --fail-with-body http://127.0.0.1:8765/investigate \
  -H 'Content-Type: application/json' \
  --data-binary @examples/incident.json
```

The API schema and interactive request form are at
`http://127.0.0.1:8765/docs`. If that port is occupied, change it in both the
server and client commands. Override the defaults with `OLLAMA_MODEL` and
`OLLAMA_BASE_URL` in the API process's environment; `.env` files are not loaded.
The configured model must support Ollama JSON-schema structured output.

## Workflow

1. Validate the incident, timezone-aware timestamps, and unique evidence IDs.
2. Select only evidence for the exact service within the inclusive time window.
3. Sort evidence chronologically and retrieve up to three local Markdown
   runbooks using lexical overlap. No matches means no runbooks are supplied.
4. Make one structured-output request to Ollama with that evidence and context.
5. Validate the output schema and reject citations outside the selected evidence.
6. Return the findings, selected evidence, and retrieved runbooks as JSON.

If no evidence matches, return a null root cause without calling the model.
An inconclusive model result can also have a null root cause. A non-null root
cause requires at least one evidence ID. References identify original records;
they do **not** prove the explanation is true. Every hypothesis needs review.

Input format: see `examples/incident.json`. Evidence kinds are `log`, `metric`,
and `deployment`; `detail` holds the supplied observation. All findings fields
are required: `suspected_root_cause`, `evidence_ids`, `recommended_actions`, and
`uncertainties`. Responses also contain `incident_id`, `evidence`, and `runbooks`.

Add curated `.md` files to `runbooks/` to extend troubleshooting guidance. The
included example and runbooks are synthetic, not a benchmark or production data.

## Tests

```sh
uv run python -m unittest discover -s tests -v
```

Tests mock Ollama's HTTP boundary while exercising the real API, filtering,
retrieval, prompt construction, output validation, and failure handling. They
do not require Ollama or a downloaded model.

## Roadmap

- Dockerize the API with reproducible dependencies and a configurable external
  Ollama endpoint.
- Add a read-only integration layer that fetches logs, metrics, and deployment
  events on command for a specified service and time window, normalizes them
  into the existing incident request, and submits them to TriageAssist.

These are future additions, not implemented features. Keep evidence collection
separate from analysis; integrations should preserve source identifiers, bound
queries, and redact secrets before submitting evidence. Remediation stays
human-controlled.

## Deliberate limits

- Local, single-worker prototype: no authentication, persistence, connectors,
  job queue, frontend, vector database, or orchestration framework. Do not expose
  it publicly. Keep one Uvicorn worker; the in-process lock permits one model
  request at a time and returns 503 when busy.
- At most 100 evidence records, 2,000 characters per observation, and 16,000
  characters of combined model context. Oversized context returns 422 rather
  than silently dropping evidence. Character limits are not tokenizer-aware;
  non-English or unusually token-dense input may exceed the model context.
- Ollama requests use a 5-second connect timeout and 120-second network
  inactivity timeout. This is not an overall job deadline. There are no automatic
  retries. Dependency failures return 502/503; timeouts return 504.
- Lexical retrieval can miss synonyms. Citation checks catch unknown IDs, not
  incorrect reasoning, fabricated claims about a valid record, or prompt
  injection. No confidence score or claim of verified root-cause accuracy.
- The assistant recommends actions only. It never executes fixes, queries live
  infrastructure, or independently gathers additional evidence. Review outputs
  and redact secrets before submitting real operational data. A remote
  `OLLAMA_BASE_URL` sends the selected evidence and runbooks to that server.

Inspired by the problem explored in
[AI-Powered-Production-Incident-Investigation-Agent](https://github.com/meghana-ganesh/AI-Powered-Production-Incident-Investigation-Agent).
This is a separate minimal implementation, not a copy of that codebase.
