#!/usr/bin/env python3
"""M4: Qoder user_memories integration layer.

Generates structured query hints that the Qoder runtime adapter can use to call
search_memory / update_memory. Since these are LLM-level tool calls (not Python
APIs), this module produces *instructions* for the runtime, not direct calls.

Two-phase design:
  Phase 1 (pre-delivery): generate search_memory queries → inject results into handoffs.
  Phase 2 (post-delivery): generate update_memory payloads → persist lessons learned.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Categories that are relevant to the development team skill.
RELEVANT_CATEGORIES = [
    "development_code_specification",
    "development_practice_specification",
    "development_test_specification",
    "development_comment_specification",
    "expert_experience",
    "common_pitfalls_experience",
    "learned_skill_experience",
    "project_tech_stack",
    "project_introduction",
]

MAX_SEARCH_QUERIES = 3
MAX_KEYWORDS_PER_QUERY = 5


def _extract_keywords(task_summary: str) -> list[str]:
    """Extract short keywords from task summary for memory search."""
    import re
    # Remove common stop words and extract meaningful tokens
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", " ", task_summary)
    tokens = [t for t in cleaned.split() if len(t) >= 2]

    # Prioritize technical terms
    tech_terms = [
        t for t in tokens
        if any(c.isupper() for c in t) or len(t) > 3 or not t.isascii()
    ]
    result = tech_terms[:MAX_KEYWORDS_PER_QUERY]
    if len(result) < 2:
        result = tokens[:MAX_KEYWORDS_PER_QUERY]
    return result


def generate_pre_delivery_queries(task_summary: str,
                                  stack_adapters: list[str] | None = None,
                                  domains: list[str] | None = None) -> list[dict]:
    """Generate search_memory query hints for pre-delivery context loading.

    Returns a list of query objects that the runtime adapter should execute.
    Each object has: {depth, query, category, keywords, purpose}.
    """
    queries: list[dict] = []
    keywords = _extract_keywords(task_summary)

    # Q1: Code specifications and practices
    queries.append({
        "depth": "shallow",
        "query": task_summary[:100],
        "category": "development_code_specification,development_practice_specification",
        "keywords": ",".join(keywords[:3]),
        "purpose": "Recall coding conventions and practices relevant to this task",
        "injectionTarget": "governanceConstraints",
    })

    # Q2: Known pitfalls and expert experience
    queries.append({
        "depth": "shallow",
        "query": task_summary[:100],
        "category": "common_pitfalls_experience,expert_experience",
        "keywords": ",".join(keywords[:3]),
        "purpose": "Recall past mistakes and expert knowledge to avoid repeating failures",
        "injectionTarget": "risksAndQuestions",
    })

    # Q3: Stack-specific knowledge (if adapters detected)
    if stack_adapters:
        adapter_kw = [a.split("-")[0] for a in stack_adapters[:3]]
        queries.append({
            "depth": "shallow",
            "query": f"technology stack: {' '.join(adapter_kw)}",
            "category": "project_tech_stack,learned_skill_experience",
            "keywords": ",".join(adapter_kw[:MAX_KEYWORDS_PER_QUERY]),
            "purpose": "Recall stack-specific configuration and lessons",
            "injectionTarget": "governanceConstraints",
        })

    return queries[:MAX_SEARCH_QUERIES]


def generate_post_delivery_update(delivery_summary: dict) -> list[dict]:
    """Generate update_memory payloads for post-delivery persistence.

    Called after a delivery completes to save lessons learned.
    Returns a list of update_memory instruction objects.
    """
    updates: list[dict] = []

    task_summary = delivery_summary.get("taskSummary", "")
    blocking_reasons = delivery_summary.get("blockingReasons", [])
    warnings = delivery_summary.get("warnings", [])
    delivery_id = delivery_summary.get("deliveryId", "")

    # Only persist if there were failures or notable warnings
    if blocking_reasons:
        content = (
            f"Delivery {delivery_id}: {task_summary[:100]}\n"
            f"Blocking issues encountered:\n"
            + "\n".join(f"  - {r}" for r in blocking_reasons[:5])
        )
        updates.append({
            "action": "create",
            "category": "common_pitfalls_experience",
            "title": f"Delivery failure: {task_summary[:60]}",
            "content": content,
            "keywords": ",".join(_extract_keywords(task_summary)[:3]),
            "usage_scenario": json.dumps([
                f"Working on similar task: {task_summary[:60]}",
                "Encountering similar blocking issues in delivery validation",
            ]),
        })

    # Persist notable warnings as expert experience
    notable_warnings = [w for w in warnings if "TOKEN-OVERBUDGET" in w or "DEGRADATION" in w]
    if notable_warnings:
        content = (
            f"Delivery {delivery_id}: {task_summary[:80]}\n"
            f"Notable warnings:\n"
            + "\n".join(f"  - {w}" for w in notable_warnings[:5])
        )
        updates.append({
            "action": "create",
            "category": "expert_experience",
            "title": f"Performance warning: {task_summary[:60]}",
            "content": content,
            "keywords": "token,budget,degradation,performance",
            "usage_scenario": json.dumps([
                "Monitoring token budget across deliveries",
                "Diagnosing performance degradation patterns",
            ]),
        })

    return updates


def build_memory_injection(query_results: list[dict]) -> dict:
    """Transform raw search_memory results into handoff-injectable format.

    Takes the results from executing the queries from generate_pre_delivery_queries
    and structures them for injection into handoff payloads.
    """
    governance_extra: list[str] = []
    risk_warnings: list[str] = []

    for result in query_results:
        purpose = result.get("purpose", "")
        memories = result.get("memories", [])
        target = result.get("injectionTarget", "governanceConstraints")

        for mem in memories:
            content = mem.get("content", "")[:300]  # Truncate to save tokens
            title = mem.get("title", "")

            if target == "governanceConstraints":
                governance_extra.append(f"[Memory: {title}] {content}")
            elif target == "risksAndQuestions":
                risk_warnings.append(f"[Past Experience: {title}] {content}")

    return {
        "hasInjection": bool(governance_extra or risk_warnings),
        "governanceExtra": governance_extra[:5],  # Cap at 5
        "riskWarnings": risk_warnings[:5],
        "memoryEvidence": {
            "queriesExecuted": len(query_results),
            "memoriesInjected": len(governance_extra) + len(risk_warnings),
        },
    }


def main() -> int:
    """CLI: generate pre-delivery queries or post-delivery updates."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_pre = sub.add_parser("pre-delivery", help="Generate search_memory queries")
    p_pre.add_argument("--task-summary", required=True)
    p_pre.add_argument("--adapters", nargs="*", default=[])

    p_post = sub.add_parser("post-delivery", help="Generate update_memory payloads")
    p_post.add_argument("--delivery-json", required=True, help="Path to delivery summary JSON")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "pre-delivery":
        queries = generate_pre_delivery_queries(args.task_summary, args.adapters)
        print(json.dumps(queries, ensure_ascii=False, indent=2))

    elif args.cmd == "post-delivery":
        summary = json.loads(Path(args.delivery_json).read_text(encoding="utf-8"))
        updates = generate_post_delivery_update(summary)
        print(json.dumps(updates, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
