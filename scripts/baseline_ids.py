"""Stable-ID extraction for baseline BPMN/OWL artifacts.

The input-contract gates compare ID sets only; they deliberately do not parse
business semantics. Two projection styles must resolve to the same IDs:

- BPMN flow nodes carry the stable ID directly in ``id``.
- OWL resources may carry a Chinese business name as the IRI local part and
  keep the canonical ASCII ID in a ``trace:稳定标识`` (or ``stableId``)
  annotation. Both forms are accepted, so a Chinese-labelled ontology still
  matches the ``ENT-*`` ids declared in ``02-领域模型.md``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

BPMN_FLOW_NODE_TAGS = {
    "task", "userTask", "serviceTask", "scriptTask", "manualTask",
    "businessRuleTask", "sendTask", "receiveTask", "callActivity",
    "subProcess", "exclusiveGateway", "inclusiveGateway", "parallelGateway",
    "eventBasedGateway", "complexGateway",
    "startEvent", "endEvent", "intermediateCatchEvent",
    "intermediateThrowEvent", "boundaryEvent",
}

OWL_RESOURCE_TAGS = {"Class", "NamedIndividual"}
TRACE_STABLE_ID_TAGS = {"稳定标识", "stableId"}


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def bpmn_flow_node_ids(path: Path) -> set[str]:
    """Collect ids of BPMN flow nodes (tasks, gateways, and events)."""
    ids: set[str] = set()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return ids
    for element in root.iter():
        if localname(element.tag) in BPMN_FLOW_NODE_TAGS:
            node_id = element.get("id")
            if node_id:
                ids.add(node_id)
    return ids


def owl_resource_ids(path: Path) -> set[str]:
    """Collect OWL resource IRI local names plus trace stable IDs."""
    ids: set[str] = set()
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return ids
    rdf_ns = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
    for element in root.iter():
        if localname(element.tag) not in OWL_RESOURCE_TAGS:
            continue
        for attr in (f"{rdf_ns}about", f"{rdf_ns}ID", "about", "ID"):
            value = element.get(attr)
            if value:
                ids.add(value.split("#")[-1].rstrip("/").rsplit("/", 1)[-1])
                break
        for child in element.iter():
            if localname(child.tag) in TRACE_STABLE_ID_TAGS:
                stable_id = (child.text or "").strip()
                if stable_id:
                    ids.add(stable_id)
    return ids
