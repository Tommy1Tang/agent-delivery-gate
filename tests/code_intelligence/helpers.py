from __future__ import annotations

from copy import deepcopy

from scripts.code_intelligence_models import SymbolRef, content_hash


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def symbol(path: str, name: str, start: int, end: int, manifest: str = HASH_A) -> dict[str, object]:
    return SymbolRef("fixture", path, name, "FUNCTION", start, end, manifest).to_dict()


def snapshot() -> dict[str, object]:
    first = symbol("app.py", "app.entry", 1, 10)
    second = symbol("app.py", "app.worker", 12, 20)
    relation = {"sourceSymbolId": first["symbolId"], "type": "CALLS", "targetSymbolId": second["symbolId"]}
    relation["relationshipId"] = content_hash(relation, excluded_keys=())
    relation.update({
        "rawRelationshipId": content_hash({"fixture": "entry-calls-worker"}, excluded_keys=()),
        "resolutionClass": "RESOLVED_INTERNAL", "sourceResolution": "DIRECT_SYMBOL", "targetResolution": "DIRECT_SYMBOL",
        "classificationOrigin": "LEGACY_RESOLVED",
    })
    raw_ids_hash = content_hash([relation["rawRelationshipId"]], excluded_keys=())
    empty_ids_hash = content_hash([], excluded_keys=())
    relationship_coverage: dict[str, object] = {
        "schemaVersion": "1.0.0", "classificationContractVersion": "1.0.0",
        "classifiableProviderRelationshipCount": 0, "resolvedInternalCount": 0, "auditedBoundaryCount": 0,
        "unresolvedInternalCount": 0, "legacyUnclassifiedCount": 0, "typeCounts": [],
        "classificationComplete": True, "internalGraphComplete": True, "boundaryClassificationComplete": True,
        "profile": {
            "nonStructuralProviderRelationshipCount": 1, "resolvedInternalRelationshipCount": 1,
            "auditedBoundaryRelationshipCount": 0, "unresolvedInternalRelationshipCount": 0,
            "rawRelationshipIdsHash": raw_ids_hash, "resolvedInternalRawIdsHash": raw_ids_hash,
            "auditedBoundaryRawIdsHash": empty_ids_hash, "unresolvedInternalRawIdsHash": empty_ids_hash,
            "accountingComplete": True,
        },
    }
    relationship_coverage["contentHash"] = content_hash(relationship_coverage)
    value: dict[str, object] = {
        "schemaVersion": "1.1.0", "snapshotId": "CIS-" + "1" * 24, "repositoryId": "fixture", "manifestHash": HASH_A,
        "sourceDigest": HASH_B, "files": [{"relativePath": "app.py", "language": "py", "size": 1, "sizeBytes": 1, "lineCount": 20, "sha256": HASH_C, "eligibility": "ELIGIBLE", "coverageStatus": "INDEXED"}],
        "symbols": [first, second], "relationships": [relation], "boundaryRelationships": [], "unresolvedInternalRelationships": [],
        "unresolvedSymbols": [], "unresolvedRelationships": [], "relationshipCoverage": relationship_coverage,
        "providerNodeInventory": {"rawCount": 2, "byLabel": {"FUNCTION": 2}, "inventoryHash": HASH_C},
        "coverage": {"complete": True, "eligibleFileCount": 1, "indexedFileCount": 1, "gapFiles": [], "requiredCaptures": [], "missingCaptures": [], "relationshipClassificationComplete": True, "unresolvedInternalRelationshipCount": 0, "auditedBoundaryRelationshipCount": 0, "providerNodeInventoryHash": HASH_C, "relationshipCoverageHash": relationship_coverage["contentHash"]},
        "freshness": {"headMatches": True, "sourceDigestMatches": True, "configMatches": True, "sourceChangedDuringAnalysis": False},
        "providerState": {
            "available": True, "schemaMatches": True, "identityVerified": True, "version": "0.0.779",
            "codecSchemaSha256": "09e1c5e0b1b58c5e02c3e55e99e438625dfeed0caf3839a5b782d9196b348e84", "configHash": HASH_C,
            "identity": {"verificationMode": "fixture-contract", "distribution": "code-graph-rag", "entryPoint": "codebase_rag.cli:app", "fixtureHash": HASH_C},
        },
        "integrity": {"valid": True}, "generatedAt": "2026-08-27T00:00:00Z"
    }
    value["contentHash"] = content_hash(value)
    return value


def trace() -> dict[str, object]:
    snap = snapshot(); first, second = snap["symbols"]
    implementation = {
        "declaration": {"relativePath": "app.py", "line": 2}, "symbolRef": first, "requirementIds": ["FR-001"],
        "role": "implementation", "testId": None, "status": "exact", "reasonCode": None, "manifestHash": HASH_A,
        "sourceDigest": HASH_B, "requirementsHash": HASH_C,
    }
    implementation["traceLinkId"] = content_hash(implementation, excluded_keys=())
    test = {
        "declaration": {"relativePath": "app.py", "line": 13}, "symbolRef": second, "requirementIds": ["FR-001"],
        "role": "test", "testId": "TEST-FR-001", "status": "exact", "reasonCode": None, "manifestHash": HASH_A,
        "sourceDigest": HASH_B, "requirementsHash": HASH_C,
    }
    test["traceLinkId"] = content_hash(test, excluded_keys=())
    value: dict[str, object] = {"schemaVersion": "1.0.0", "traceBridgeId": "CTB-" + "2" * 24, "manifestHash": HASH_A, "sourceDigest": HASH_B, "requirementsHash": HASH_C, "links": [implementation, test], "rejected": [], "generatedAt": "2026-08-27T00:00:00Z"}
    value["contentHash"] = content_hash(value)
    return value


def clone(value):
    return deepcopy(value)
