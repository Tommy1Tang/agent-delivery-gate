# OpenClaw Runtime Adapter

Use this adapter when loading `software-development-team` into an OpenClaw-style agent runtime.

## Mapping

- Load roles from `assets/config/agent-team-config.json` or YAML.
- Bind each `promptFile` to the corresponding role id.
- Use `mode.unified-large-delivery.route` as the default route.
- Use `harness.schemas` for structured payload validation.

## Execution Rules

- Dispatch one role per isolated session when supported.
- Store handoff payloads and role results as run artifacts.
- Persist `evidence-ledger.json` for audit and replay.
- Run `scripts/validate_delivery.py` before final completion.

