"""Shared, deterministic bootstrap/normal code-gate mode resolver."""

from __future__ import annotations

from typing import Mapping

try:
    from .bootstrap_code_intelligence import ACTIVATED_VERSION, STARTING_VERSION, activation_token_id, compare_process_versions, validate_bootstrap_inventory
except ImportError:
    from bootstrap_code_intelligence import ACTIVATED_VERSION, STARTING_VERSION, activation_token_id, compare_process_versions, validate_bootstrap_inventory


def _code(ledger: Mapping[str, object]) -> Mapping[str, object]:
    value = ledger.get("codeIntelligence")
    return value if isinstance(value, Mapping) else {}


def explain_code_gate_mode(ledger: Mapping[str, object], process: Mapping[str, object], bootstrap_inventory: Mapping[str, object] | None = None) -> dict[str, object]:
    code = _code(ledger)
    starting = str(code.get("startingProcessVersion", ledger.get("startingProcessVersion", "")))
    activated = str(code.get("activatedVersion", ledger.get("activatedVersion", ACTIVATED_VERSION)))
    process_version = str(process.get("version", ""))
    delivery_id = str(code.get("deliveryId", ledger.get("deliveryId", ledger.get("taskName", ""))))
    repository_id = str(code.get("repositoryId", ledger.get("repositoryId", "")))
    has_bootstrap_request = bootstrap_inventory is not None or any(key in code for key in ("bootstrapInventory", "baselineStatement"))
    try:
        compare_process_versions(starting, activated)
        compare_process_versions(process_version, ACTIVATED_VERSION)
    except ValueError:
        return {"mode": "blocked", "code": "BOOTSTRAP_VERSION_INVALID", "reasons": ["strict process versions are missing or invalid"]}
    if starting == ACTIVATED_VERSION:
        if has_bootstrap_request:
            return {"mode": "blocked", "code": "BOOTSTRAP_ALREADY_CONSUMED", "reasons": ["deliveries starting at 1.1.0 must use normal C-CODE-05/06"]}
        return {"mode": "normal", "code": "NORMAL_CODE_GATES", "reasons": []}
    if starting != STARTING_VERSION or activated != ACTIVATED_VERSION or process_version not in {STARTING_VERSION, ACTIVATED_VERSION}:
        return {"mode": "blocked", "code": "BOOTSTRAP_VERSION_INVALID", "reasons": ["the only activation window is 1.0.0 -> 1.1.0"]}
    if bootstrap_inventory is None:
        return {"mode": "blocked", "code": "BOOTSTRAP_EVIDENCE_INCOMPLETE", "reasons": ["bootstrap inventory is required"]}
    token = activation_token_id(repository_id, STARTING_VERSION, ACTIVATED_VERSION)
    current_activation = code.get("activation")
    current_marker = code.get("consumedMarker")
    histories = []
    for key in ("activationHistory", "consumedMarkerHistory"):
        value = code.get(key)
        if isinstance(value, list):
            histories.extend(item for item in value if isinstance(item, Mapping))
    for historical in histories:
        if historical.get("tokenId") == token and historical.get("deliveryId") != delivery_id:
            return {"mode": "blocked", "code": "BOOTSTRAP_ALREADY_CONSUMED", "reasons": ["the repository/version token was consumed by another delivery"]}
    inventory_result = validate_bootstrap_inventory(bootstrap_inventory)
    if inventory_result["status"] != "pass":
        codes = inventory_result["codes"]
        return {"mode": "blocked", "code": codes[0], "reasons": codes}
    if bootstrap_inventory.get("repositoryId") != repository_id or bootstrap_inventory.get("deliveryId") != delivery_id:
        return {"mode": "blocked", "code": "BOOTSTRAP_HASH_MISMATCH", "reasons": ["inventory repository/delivery binding mismatch"]}
    for current in (current_activation, current_marker):
        if current is None:
            continue
        if not isinstance(current, Mapping) or current.get("tokenId") != token or current.get("repositoryId") != repository_id or current.get("deliveryId") != delivery_id or current.get("consumed") is not True:
            return {"mode": "blocked", "code": "BOOTSTRAP_ALREADY_CONSUMED", "reasons": ["activation/marker does not bind to the current delivery"]}
    return {"mode": "bootstrap", "code": "BOOTSTRAP_NOT_APPLICABLE", "reasons": []}


def resolve_code_gate_mode(ledger: Mapping[str, object], process: Mapping[str, object], bootstrap_inventory: Mapping[str, object] | None = None) -> str:
    return str(explain_code_gate_mode(ledger, process, bootstrap_inventory)["mode"])
