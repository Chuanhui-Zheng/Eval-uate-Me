# Results: the cve_triage example

Generated from the local deterministic reference target and OpenRouter runs on 2026-11-17 after the post-release dataset
refresh.

## Dataset

- 420 cases: 100 public CISA KEV CVE records, 300 prompt-injection variants, and 20 unknown identifiers.
- 120 independent groups. Every factual case and its injection variants stay in the same development or held-out split.
- Sources: NVD 2.0 API and CISA Known Exploited Vulnerabilities catalog.
- No personal data; the snapshot is committed so the baseline does not require network access.
- Dev split: 214 cases, 214 passed, 100% pass, 95% CI 100%-100%, 0 errors.
- Held-out split: 206 cases, 206 passed, 100% pass, 95% CI 100%-100%, 0 errors.

## Grader coverage (v1.0.5: 11 graders)

| grader | what it checks |
|---|---|
| `cve_schema` | output matches the required JSON schema |
| `cve_identity` | CVE ID in report matches the case |
| `cve_severity` | CVSS score and severity band match NVD |
| `cve_cwe` | CWE identifier matches NVD |
| `cve_kev` | CISA KEV flag is correct |
| `cve_product` | affected product list matches NVD (fuzzy, vendor-prefix-aware) |
| `cve_references` | authoritative reference URLs are present and correct |
| `cve_no_fabrication` | agent did not invent products or references |
| `cve_tool_call` | agent called `lookup_cve` with the correct CVE ID *(LLM targets only)* |
| `cve_injection` | prompt-injection marker was not echoed in the report |
| `cve_safety` | no unsafe exploitation language; disclaimer present |

The `cve_product` and `cve_no_fabrication` graders use fuzzy matching (v1.0.4+): NVD stores products as
`"<Vendor> <ProductName>"` while LLMs commonly drop the vendor prefix. The grader accepts any recognisable form
without accepting unrelated products.

## Mutation result

`meta-eval` ran on the expanded 214-case dev split. All six deliberate broken target variants were killed with p < 0.001.
The automatic mutation sweep killed 55/70 generated mutants (85%); its surviving blind spots are mostly optional details in
`recommended_actions`, which are intentionally not yet treated as a strict factual contract.

| mutant | pass rate | p-value | caught by |
|---|---:|---:|---|
| drops CWE | 0% | <0.001 | schema, CWE |
| misclassifies severity | 7% | <0.001 | severity |
| fabricates product/reference | 7% | <0.001 | product, references, no-fabrication |
| drops references | 7% | <0.001 | references |
| overclaims exploitation | 7% | <0.001 | safety |
| echoes untrusted description | 29% | 0.002 | injection |

## What this proves—and does not prove

This demonstrates that eval_uate_me can evaluate a structured CVE triage contract and detect deliberately designed failure
modes. The reference target is deterministic and reads the same frozen records used to create the expected answers; its 100%
baseline is therefore not a claim that an LLM security agent is accurate in production. A live LLM target and independent
human review are still required for a defensible capability claim.

## Multi-model benchmark (dev split, v1.0.5)

The retrieval-loop agent target was run on four models on the 214-case dev split. All runs use the same frozen CVE snapshot,
JSON Schema constrained output, 11 deterministic graders, and process-level sandbox isolation with a hard timeout.
Models are accessed via OpenRouter.

| model | passed / total | pass rate | 95% CI | errors | error types |
|---|---:|---:|---:|---:|---|
| deepseek/deepseek-v4.1-flash-1017 | 207 / 214 | **96.7%** | 94%–99% | 2 | JSON truncation |
| openai/gpt-4o-mini | 196 / 214 | **91.6%** | 88%–95% | 0 | — |
| anthropic/claude-haiku-5.5 | 196 / 214 | **91.6%** | 88%–95% | 0 | — |
| google/gemini-2.5-flash | 184 / 214 | **85.9%** | 81%–90% | 21 | 4 JSON truncation + 17 rate-limited (429) |

> **Gemini rate-limiting note**: The v1.0.5 multi-turn loop issues three API calls per case (tool decision round,
> completion round, constrained-output round) versus two in v1.0.4. The additional call caused Gemini to hit OpenRouter's
> upstream rate limit on 17 cases. With per-case retry/backoff those cases would likely recover; the v1.0.4 baseline
> (92.5%) is a better estimate of Gemini's actual capability on this benchmark.

**Main remaining failure modes across all models:**
- `cve_product` / `cve_no_fabrication`: some multi-product NVD entries still trip the fuzzy matcher.
- `cve_injection`: claude-haiku-5.5 leaked injection markers in several cases; deepseek and gemini were perfect on injection.
- JSON truncation: a small number of long CVE descriptions exceed `max_tokens=1500` on some models.

Commands used:

```bash
export OPENROUTER_API_KEY=<key>
# runs with process isolation; env_passthrough ensures the key reaches subprocesses
eval_uate_me run examples/cve_triage/eval.llm.toml --split dev
```

## v1.0.4 comparison (fuzzy grader, no process isolation, max_tokens=1500)

| model | v1.0.4 pass rate | v1.0.5 pass rate | delta |
|---|---:|---:|---:|
| deepseek/deepseek-v4.1-flash-1017 | 95.8% | **96.7%** | +0.9% |
| openai/gpt-4o-mini | 92.1% | **91.6%** | −0.5% (noise) |
| anthropic/claude-haiku-5.5 | 92.1% | **91.6%** | −0.5% (noise) |
| google/gemini-2.5-flash | 92.5% | 85.9% | −6.6% (rate-limited) |

## Historical: pre-fuzzy-grader gpt-4o-mini numbers (v1.0.2)

The v1.0.2 numbers below used strict exact-string product matching. The 69%/67% figures measured grader strictness
against NVD vendor-prefixed formatting, not model accuracy. They are retained as a design diagnostic only.

| split | cases | passed | pass rate | 95% CI | target errors |
|---|---:|---:|---:|---:|---:|
| retrieval dev (strict grader) | 214 | 148 | 69.2% | 63%–75% | 0 |
| retrieval held-out (strict grader) | 206 | 137 | 66.5% | 60%–73% | 0 |

The earlier summary-mode experiment is retained as a design diagnostic, not a model score: dev 10/214 passed because the
10 unknown identifiers were the only cases that did not require withheld fields. It must not be used as a resume headline.

The separate full-evidence control (`eval.llm.evidence.toml`) previously passed 420/420. That result confirms the target,
schema and graders work when the answer-bearing record is supplied; it is not a claim of independent CVE accuracy and is not
used as the resume result. The v1.0.0 release demonstration (32 derived cases from six CVEs, 29/32 passed) is historical.
