# agent-delivery-gate

> **A vibe-coding skill that ships.** Describe what you want in plain language — a team of 15 agent roles takes it from requirement to tested, reviewed, documented, deployable delivery. Deterministic gates decide when it is actually *done*.

[![tests](https://github.com/Tommy1Tang/agent-delivery-gate/actions/workflows/tests.yml/badge.svg)](https://github.com/Tommy1Tang/agent-delivery-gate/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#verify-it-yourself)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What this is

A reusable **software-delivery skill** for AI coding agents. You give it a requirement in natural language; it runs a full delivery pipeline and produces the real artefacts a project needs:

```text
your requirement
      │
      ▼
  environment preflight → input contract → requirements
  → architecture → data / API contract / performance / UI design
  → implementation → unit + integration tests → E2E
  → code review → security review → release readiness
  → documentation → independent audit → delivery gate
      │
      ▼
  docs/01..19 + evidence ledger + a mechanically derived PASS or BLOCK
```

It is **not** a chat wrapper. It is 21 process nodes, 15 role contracts, 35 document templates and 22 JSON Schema contracts, driven by a process model that the scripts re-read every round.

---

## Why gates, and not just "the agent says it's done"

Vibe coding has one real failure mode: you cannot tell a finished delivery from a confident one. A run ends with *"I've implemented the feature and everything works."* That claim is unfalsifiable — which requirement did this code implement? Which test covers it? Did the change stay in the approved scope? Was "all tests pass" measured or guessed?

So the skill does the work, and **deterministic scripts own the verdicts.**

> **Core invariant:** an LLM summary, an embedding, or a generated query may *assist exploration*, but none of them may ever be submitted as `PASS` evidence for a gate.

That is what makes unattended delivery trustworthy: the agent cannot mark its own homework.

---

## Quick start

```bash
git clone https://github.com/Tommy1Tang/agent-delivery-gate.git
cd agent-delivery-gate

# 1. It runs on the standard library alone - no pytest, no install, no network, no services.
#    Requires Python 3.11+ (the code uses datetime.UTC). CI covers 3.11 and 3.12 on Linux,
#    plus 3.12 on Windows.
python run_tests.py
```

> **Windows note:** delivery documents have Chinese file names, so set UTF-8 before running
> the CLIs — `$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"` (or pass `-X utf8`), otherwise
> a non-UTF-8 console code page makes the report printer raise `UnicodeEncodeError`.

Expected:

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

Then drive a delivery:

```bash
# 2. Turn a requirement into a routed plan + handoff payloads
python scripts/orchestrate.py \
  --skill-root . \
  --project-root /path/to/your-project \
  --task-summary "给订单系统增加批量导入功能" \
  --output-dir .qoder/skill-state --json

# 3. Ask the process model what happens next - every round, never from memory
python scripts/next_step.py --skill-root . --project-root . --json

# 4. At the end, the delivery gate decides
python scripts/validate_delivery.py --skill-root . --project-root /path/to/your-project
```

Register the directory as a skill in your agent runtime and invoke it with a requirement — see [`SKILL.md`](SKILL.md) for the full contract.

---

## Three capabilities that make it work

### 1 · Automatic code graph

Before any change, the skill builds a **symbol-and-relationship graph** of your repository and keeps it as a normalised, hash-addressed snapshot. That graph is what answers "what does this code actually do" without an LLM guessing.

```bash
# Build the graph (offline, deterministic, content-hashed)
python scripts/build_code_index.py \
  --project-root /path/to/your-project \
  --output-dir .qoder/code-index \
  --config assets/config/code-intelligence.json --json
```

Then query it in **plain Chinese or English** — seven deterministic intents, no model in the loop:

| Intent | You ask |
|---|---|
| `definition` | `X 在哪里定义？` / `where is X defined?` |
| `callers` | `谁调用 X？` / `who calls X?` |
| `callees` | `X 调用了谁？` / `what does X call?` |
| `references` | `谁引用 X？` |
| `contains` | `模块 X 包含什么？` |
| `implements_requirement` | `FR-003 由什么实现？` |
| `tests_for` | `哪些测试覆盖 X？` |

Real output, reproduced by the runnable [`demo_code_graph.py`](demo_code_graph.py):

```console
$ python demo_code_graph.py
fixture graph: 2 symbols, 1 relationships

$ query_code_graph.py --intent definition --target app.worker
{ "queryStatus": "ANSWERED", ... "definition returned 1 exact symbol(s)" }

$ query_code_graph.py --intent callers --target app.worker
{ "queryStatus": "ANSWERED", ... "callers returned 1 exact symbol(s)" }

$ query_code_graph.py --intent implements_requirement --target FR-001
{ "queryStatus": "ANSWERED", ... "implements_requirement returned 1 exact symbol(s)" }

$ query_code_graph.py --intent tests_for --target app.worker
{ "queryStatus": "ANSWERED", ... "tests_for returned 1 exact symbol(s)" }
```

An ambiguous symbol returns **candidates**, not a coin flip. A stale snapshot or incomplete coverage returns `UNKNOWN`, not a plausible answer.

### 2 · Automatic verification

Every claim the delivery makes is checked by a script, not by the model. The graph produces two hard facts:

**Blast radius, before you touch anything:**

```bash
python scripts/analyze_code_impact.py \
  --snapshot .qoder/code-index/code-index-snapshot.json \
  --trace-bridge .qoder/code-index/code-trace-bridge.json \
  --requirement FR-003 --artifact-root . --json
```

It answers exactly one of `FOUND` / `NO_IMPACT` / `UNKNOWN`. `NO_IMPACT` is only permitted when the seed is unique, the snapshot is fresh, coverage is complete, and traversal was not truncated — otherwise you get `UNKNOWN`, which **blocks**.

**Scope reconciliation, after:**

```bash
python scripts/reconcile_code_changes.py ...   # actual vs approved changeSet
```

Did the change stay inside the approved files, symbols and relations? Any undeclared file, symbol or relation regression fails the reconciliation. Then the seven gates (`C-CODE-01..07`) and `validate_delivery.py` issue the final verdict.

### 3 · Automatic testing

Tests are not optional here — they are a **gate input**. The pipeline writes test cases and reports as first-class deliverables, and `validate_delivery.py` enforces hard thresholds before a delivery may pass:

| Threshold | Requirement |
|---|---|
| Unit coverage | ≥ 90% |
| Integration coverage | ≥ 80% |
| Test pass rate | 100% |
| E2E pass rate | 100%, with P0 acceptance criteria covered |

Test IDs are stable and unique repo-wide, and the graph links each requirement to the test that covers it (`--intent tests_for`) — so "it's tested" is a query result, not a claim. The example delivery in [`docs/`](docs/) shows the full set: unit cases and report, integration cases and report, E2E cases and report.

---

## What lands in your project

The pipeline writes real deliverables, not a summary. [`docs/`](docs/) in this repo contains a **complete example delivery** produced this way for *MES Lite*, a generic discrete-manufacturing execution system — requirements, design, API contract, UI spec, test cases and reports, code and security review, deployment, observability, and an independent audit.

Requirements carry stable IDs (`CAP-001`, `FR-001`, `AC-001`) that are reused verbatim across design, contract, tests and audit — so the traceability claim can be **checked by reading**, not trusted.

---

## The four workflows

| Workflow | Triggered when |
|---|---|
| `forward-development` | Building a new feature or a whole project |
| `change-management` | Requirements or baseline changed |
| `security-governance` | Security assessment and remediation |
| `incident-management` | Incident, outage, recovery |

Routing is decided by the process model, not by the agent's mood.

---

## Architecture: three graphs and a bridge

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

### The gates

| Gate | Mechanical criterion |
|---|---|
| `C-CODE-01` | Provider version / distribution identity / schema and artifact hashes are trustworthy and fresh |
| `C-CODE-02` | Eligible files and captures complete; internal relations fully resolved; relationship count conserved |
| `C-CODE-03` | Trace markers strictly legal — no orphan, ambiguous, or duplicate test IDs |
| `C-CODE-04` | Every Must-FR and P0-AC has both an exact implementation link and a test link |
| `C-CODE-05` | Pre-change: a current impact analysis must exist before code may be modified |
| `C-CODE-06` | Post-change: a real before/after reconciliation must pass |
| `C-CODE-07` | Inventory, baseline, activation and ledger references are replayable |

A gate returns `PASS`, `BLOCK`, `UNKNOWN`, or `NOT_APPLICABLE`. **`UNKNOWN` is not a soft pass** — it blocks, with a reason code and remediation hint. There is deliberately no path where "the agent was confident" becomes `PASS`.

Every role run, command, artifact and gate verdict is appended to an **append-only evidence ledger** (`scripts/write_evidence_ledger.py`), which is what makes the delivery auditable after the fact.

---

## What's in the box

```text
scripts/        53 Python modules (~16k lines) — the deterministic machinery
schemas/        22 JSON Schema contracts (handoff, role result, quality gate, audit, ledger)
assets/
  config/       process model (21 nodes / 15 roles / 4 workflows), ontology
  prompts/      15 role contracts
  templates/    35 delivery-document templates
  design.md     a reusable design-system spec (46 colour tokens, 29 sections)
references/     43 governance and workflow documents
docs/           a complete example delivery for a generic MES (19 documents)
tests/          83 tests covering gate logic, determinism and policy
demo_code_graph.py   runnable demo of the code-graph queries shown above
```

---

## Design principles

1. **The agent does the work; scripts decide if it's done.** Verdicts are never self-issued.
2. **The process model is executable.** `next_step.py` recomputes the current node from the model and the filesystem — the workflow is never recalled from chat history.
3. **`UNKNOWN` beats a guess.** Insufficient evidence blocks rather than passes.
4. **Rework is targeted.** A failed gate routes to the role owning the root cause, with a per-root-cause retry cap.
5. **The gate cannot be talked past.** A delivery completes only when `validate_delivery.py` exits `0`.

---

## Scope and honest limitations

- **Deliverables, not a running app.** The skill produces the design, contracts, code changes, tests and evidence for the target project. This repository is the skill itself plus one worked example — it is not a hosted service and contains no UI.
- **Static, single-repository analysis.** Dynamic dispatch, reflection and runtime DI are not fully resolvable; when coverage cannot be proven the framework returns `UNKNOWN` instead of guessing.
- **The example delivery is illustrative.** The test counts and coverage figures in `docs/` demonstrate report format. The framework's own real result is the 83/83 from `python run_tests.py`.
- **Runtime adapters differ.** Dispatch behaviour varies between agent runtimes (isolated subagent sessions vs. single-session fallback); see `references/runtime-adapters/`.

---

## License

MIT — see [LICENSE](LICENSE).
