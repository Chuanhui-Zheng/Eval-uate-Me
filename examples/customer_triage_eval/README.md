# Evaluate a GitHub customer-support agent

This example evaluates the public [`devala-g/langgraph-customer-triage`](https://github.com/devala-g/langgraph-customer-triage) repo with `eval-uate-me`.
The checked-out source is in `agent-source/`. The adapter returns category, customer-facing draft, confidence, final decision,
and a graph-node trace. The deterministic grader checks the declared category, confidence range, route consistency, and
that a reply exists. The LLM judge scores correctness, helpfulness, and safety. Both use OpenRouter through
`OPENROUTER_API_KEY`. Each ticket makes multiple paid model calls.

## Commands

Run from the repository root:

```bash
python3.12 -m venv .venv-customer-eval312
source .venv-customer-eval312/bin/activate
python -m pip install --upgrade pip
python -m pip install eval-uate-me==1.0.8
python -m pip install -r examples/customer_triage_eval/agent-source/requirements.txt
python -m pip install sentence-transformers langchain-openai
export OPENROUTER_API_KEY="你的 OpenRouter API Key"
export LANGSMITH_TRACING=false
export PYTHONPATH="$PWD/examples${PYTHONPATH:+:$PYTHONPATH}"
eval_uate_me check examples/customer_triage_eval/eval.toml
eval_uate_me lint examples/customer_triage_eval/eval.toml
eval_uate_me run examples/customer_triage_eval/eval.toml
```

Regenerate the 100 cases at any time with `python examples/customer_triage_eval/build_cases.py`.

The first Chroma embedding initialization may download the embedding model. `LANGSMITH_TRACING=false` prevents sending
traces to LangSmith; enable it only if you have configured LangSmith credentials and want hosted observability.

After the run, open the `report.html` inside the printed run directory. `results.jsonl` contains each ticket's output,
scores, reasons, and graph-node trace. This adapter records LangGraph node steps. It does not currently expose nested
ReAct tool spans in the eval trace; those require LangSmith tracing or extending the agent to return tool messages.

## How to read the evaluation

- `support_contract` is deterministic: expected category, confidence range, consistency with the 0.7 routing threshold,
  and a non-empty reply.
- `reply_quality` is a semantic LLM judge: correctness, helpfulness, and safety. Its judgment is a signal to review, not
  ground truth; calibrate it against human labels before treating its pass rate as a product KPI.
- The included 100 cases are a demonstration set, not a statistically representative benchmark. Review and expand them
  before comparing models or making release decisions.

## Evaluation type and observed run

This is a **closed reference / golden-label classification eval** for the ticket category and routing contract, plus an
**open-ended semantic response eval** using an LLM-as-a-judge. The deterministic grader checks category, confidence,
route consistency, and reply presence. The judge checks correctness, helpfulness, and safety against each case's policy
context. The agent itself also uses an LLM, so one case exercises both model behavior and model-based grading.

Run recorded on 2026-11-23 with `openai/gpt-4o-mini` through OpenRouter:

- 100 cases; 90 passed (90% overall; 95% CI 84%–96%).
- 98 cases returned an answer; 90 passed among those (91.8%). Two cases failed before producing output with ChromaDB
  runtime errors (`KeyError: 'ephemeral'` and `RustBindingsAPI` missing `bindings`).
- By scenario: billing 37/40, technical 40/40, vague tickets 13/20.
- Main failures: vague tickets were sometimes classified as technical; one billing ticket was classified as vague;
  the judge also flagged unsupported account/service-status claims and overly specific advice for vague requests.
- Median latency was 3.32 seconds; maximum was 112.1 seconds. The result manifest did not capture API token usage or
  cost, so its `$0` cost field does not mean the OpenRouter calls were free.

The 100 tickets are synthetic paraphrases across 40 billing, 40 technical, and 20 vague scenarios. They are a useful
demo and regression set, not 100 independent real-world customer intents. Running the command writes detailed outputs,
traces and an HTML report beneath `examples/customer_triage_eval/runs/`. The recorded HTML report and summary are also
included in the repository: [`report`](reports/customer-triage-2026-11-23.html) ·
[`summary`](reports/customer-triage-2026-11-23-summary.json).
