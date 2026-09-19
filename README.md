# agent-delivery-gate

> **Deterministic delivery gates for AI coding agents.**
> When an agent says "done", this framework decides whether that is *true* — using machine-checkable evidence instead of the agent's own summary.

[![tests](https://img.shields.io/badge/tests-83%20passing-brightgreen)](#verify-it-yourself)
[![python](https://img.shields.io/badge/python-3.12-blue)](#verify-it-yourself)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## The problem

Coding agents are good at producing code and bad at proving it is finished. A typical run ends with *"I've implemented the feature and everything works."* That claim is unfalsifiable:

- Which requirement did this code actually implement?
- Which test actually covers it?
- Did the change stay inside the scope that was approved?
- Is the agent's "all tests pass" a real measurement or a confident guess?

**agent-delivery-gate externalises that state.** The LLM does analysis and implementation; deterministic scripts own the facts and the verdicts.

> **Core invariant:** an LLM summary, an embedding, or a generated query may *assist exploration*, but none of them may ever be submitted as `PASS` evidence for a gate.

---

## What it does

| Capability | Entry point |
|---|---|
| Route a request into one of 4 delivery workflows | `scripts/orchestrate.py`, `scripts/next_step.py` |
| Query code structure in natural language | `scripts/query_code_graph.py` |
| Link requirement → code symbol → test with exact IDs | `scripts/materialize_trace_links.py` |
| Compute blast radius **before** changing code | `scripts/analyze_code_impact.py` |
| Reconcile actual changes against the approved `changeSet` **after** | `scripts/reconcile_code_changes.py` |
| Derive the current workflow node mechanically | `scripts/next_step.py` |
| Gate the delivery on coverage / E2E / review / traceability | `scripts/validate_delivery.py` |
| Append-only evidence ledger for audit | `scripts/write_evidence_ledger.py` |

### Architecture: three graphs and a bridge

```text
Requirement graph ──┐
                    ├──► TraceBridge ──► Code symbol graph
Delivery graph ─────┘                        │
                                             └──► tests / impact / diff
```

| Layer | Authority | Constraint |
|---|---|---|
| Requirement graph | PRD, plus `model-spec` / RDF / BPMN / OWL when present | Source of truth for requirements |
| Delivery graph | `assets/config/skill-process.json` + evidence ledger | Source of truth for process & gates |
| Code symbol graph | Normalised manifest/snapshot from an offline symbol index | Derived and rebuildable — never authoritative |
| TraceBridge | Explicit Requirement → Symbol → Test links | Only explicit, unique, verifiable links reach a gate |

---

## Verify it yourself

No database, no server, no API key, no network. Pure standard-library Python.

```bash
git clone <this-repo>
cd agent-delivery-gate

# 83 tests, ~30s, standard library only - no pytest, no network, no services
python run_tests.py
```

Expected output:

```text
================================================================
agent-delivery-gate test suite
  modules  : 10
  tests    : 83
  failures : 0
  errors   : 0
  skipped  : 0
================================================================
RESULT: OK
```

`run_tests.py` exists because several suites drive CLI scripts that print
structured JSON to stdout; with plain `unittest discover` that output
interleaves with the runner's report and hides the summary. Use
`python run_tests.py -v` if you want the raw per-module output.

Then watch the gate logic refuse to guess. The impact analyser returns exactly one of `FOUND`, `NO_IMPACT`, `UNKNOWN` — and `NO_IMPACT` is only permitted when the seed is unique, the snapshot is fresh, coverage is complete, and traversal was not truncated:

```bash
python scripts/analyze_code_impact.py \
  --snapshot tests/fixtures/code-intelligence/polyglot/snapshot.json \
  --trace-bridge tests/fixtures/code-intelligence/polyglot/trace-bridge.json \
  --requirement FR-001 \
  --artifact-root . \
  --json
```

---

## The gates

Seven code gates, each bound to a mechanical criterion rather than a judgement call:

| Gate | Mechanical criterion |
|---|---|
| `C-CODE-01` | Provider version / distribution identity / schema and artifact hashes are trustworthy and fresh |
| `C-CODE-02` | Eligible files and captures are complete; internal relations fully resolved; relationship count conserved |
| `C-CODE-03` | Trace markers are strictly legal — no orphan, ambiguous, or duplicate test IDs |
| `C-CODE-04` | Every Must-FR and P0-AC has both an exact implementation link and a test link |
| `C-CODE-05` | Pre-change: a current impact analysis must exist before code may be modified |
| `C-CODE-06` | Post-change: a real before/after reconciliation must pass |
| `C-CODE-07` | Inventory, baseline, activation and ledger references are replayable |

A gate may return `PASS`, `BLOCK`, `UNKNOWN`, or `NOT_APPLICABLE`. **`UNKNOWN` is not a soft pass** — it blocks, and it carries a reason code and a remediation hint. There is deliberately no path where "the agent was confident" becomes `PASS`.

---

## What's in the box

```text
scripts/        51 Python modules (~16k lines) — the deterministic machinery
schemas/        22 JSON Schema contracts (handoff, role result, quality gate, audit, ledger)
assets/
  config/       process model (19 nodes / 15 roles / 4 workflows), ontology, code-intelligence config
  prompts/      15 role prompt contracts
  templates/    35 delivery-document templates
  constitution.md, tech.md, design.md   governance + design-system layer
references/     43 governance and workflow documents
docs/           an example generated delivery for a generic MES (see below)
tests/          83 tests covering gate logic, determinism, and policy
```

---

## Example delivery output

The `docs/` directory contains a **complete example delivery** produced by this framework for *MES Lite*, a generic discrete-manufacturing execution system. It shows what the process actually emits end to end:

```text
requirements → architecture → data contract → UI spec
→ implementation → unit/integration tests → E2E → code & security review
→ deployment → observability → independent audit → delivery gate
```

Requirements carry stable IDs (`CAP-001`, `FR-001`, `AC-001`) that are reused verbatim in the design, contract, test and audit documents — so the traceability claim can be checked by reading them rather than trusting it.

---

## Design principles

1. **Facts over narration.** Scripts own verdicts; the model owns reasoning.
2. **The process model is executable.** `scripts/next_step.py` recomputes the current node from the process model and the filesystem each round — the workflow is never recalled from chat history.
3. **`UNKNOWN` beats a guess.** Insufficient evidence blocks rather than passes.
4. **Rework is targeted, not wholesale.** A failed gate routes back to the specific role that owns the root cause, with a per-root-cause retry cap.
5. **The delivery gate cannot be talked past.** A delivery reaches `completed` only when `validate_delivery.py` exits `0`.

---

## Scope and honest limitations

- **Single-repository, offline, static analysis.** Dynamic dispatch, reflection and runtime dependency injection are not fully resolvable; when coverage cannot be proven the framework returns `UNKNOWN` rather than guessing.
- **It is a harness, not a product.** There is no UI and no hosted service. It is driven from the CLI and from an agent runtime.
- **Runtime adapters vary.** Dispatch behaviour differs between agent runtimes (isolated subagent sessions vs. single-session fallback); the adapters under `references/runtime-adapters/` document the trade-offs.
- **The example delivery in `docs/` is illustrative**, generated to demonstrate the process. It is not a production MES.

---

## License

MIT — see [LICENSE](LICENSE).
