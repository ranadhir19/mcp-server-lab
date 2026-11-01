#!/usr/bin/env python3
"""audit.py — deterministic, model-free measurements of the two schema
designs. Three audits:

  1. Adversarial calls. Ten careless-or-confused calls per version
     (missing arguments, unknown ids, wrong types, nonsense actions).
     Counted: cleanly rejected (isError) vs silently accepted.
  2. Result bloat. The 16 ground-truth task calls are executed on both
     versions and the returned text is totalled in bytes.
  3. Lexical confusability (a proxy, labelled as one). For each task,
     the token overlap (Jaccard) between the correct tool's name +
     description and the most similar wrong tool's. Higher = the
     schema text itself makes tools easier to confuse.

Run: python3 audit.py   (prints a table, writes audit_results.json)
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MCPClient
import tasks as T
from run_trials import oracle_call, inspect_state

ADVERSARIAL = {
    "v1": [
        ("create with no body text", "note", {"action": "create", "title": "X"}),
        ("create with an extra argument", "note",
         {"action": "create", "title": "X", "text": "Y", "priority": "high"}),
        ("read a missing id", "get", {"id": "n99"}),
        ("update a missing id", "note", {"action": "update", "id": "n99", "text": "z"}),
        ("delete a missing id", "note", {"action": "delete", "id": "n99"}),
        ("search with an empty query", "notes", {"query": ""}),
        ("get by title only", "get", {"title": "Meeting notes"}),
        ("create with a numeric title", "note", {"action": "create", "title": 42, "text": "Y"}),
        ("nonsense action string", "note", {"action": "frobnicate", "id": "n1"}),
        ("no arguments at all", "note", {}),
    ],
    "v2": [
        ("create with no body", "create_note", {"title": "X"}),
        ("create with an extra argument", "create_note",
         {"title": "X", "body": "Y", "priority": "high"}),
        ("read a missing id", "get_note", {"id": "n99"}),
        ("update a missing id", "update_note", {"id": "n99", "body": "z"}),
        ("delete a missing id", "delete_note", {"id": "n99"}),
        ("search with no query", "search_notes", {}),
        ("get by title instead of id", "get_note", {"title": "Meeting notes"}),
        ("create with a numeric title", "create_note", {"title": 42, "body": "Y"}),
        ("update with no id", "update_note", {"body": "z"}),
        ("delete with no arguments", "delete_note", {}),
    ],
}


def adversarial(version):
    client = MCPClient(version); client.initialize()
    rows, rejected = [], 0
    for label, name, args in ADVERSARIAL[version]:
        _, is_error = client.call_tool(name, args)
        rejected += is_error
        rows.append({"call": label, "rejected": bool(is_error)})
    state = inspect_state(client, version)
    client.close()
    mutated = len(state) != 6  # seed size is 6
    return {"rejected": rejected, "accepted": len(rows) - rejected,
            "n": len(rows), "store_mutated_by_bad_calls": mutated,
            "rows": rows}


def bloat(version):
    client = MCPClient(version); client.initialize()
    total, per = 0, {}
    for task in T.TASKS:
        name, args = oracle_call(task, version)
        text, _ = client.call_tool(name, args)
        per[task["id"]] = len(text)
        total += len(text)
    client.close()
    return {"total_bytes": total, "per_task": per}


def _tokens(tool):
    s = tool["name"].replace("_", " ") + " " + tool["description"]
    return set(re.findall(r"[a-z]+", s.lower()))


def confusability(version):
    probe = MCPClient(version); probe.initialize()
    tools = probe.list_tools(); probe.close()
    toks = {t["name"]: _tokens(t) for t in tools}
    correct = {}
    for task in T.TASKS:
        if version == "v2":
            correct[task["id"]] = T.V2_TOOL[task["intent"]]
        else:
            correct[task["id"]] = T.V1_MAP[task["intent"]][0]
    scores = []
    for task in T.TASKS:
        c = toks[correct[task["id"]]]
        worst = 0.0
        for name, tk in toks.items():
            if name == correct[task["id"]]:
                continue
            j = len(c & tk) / max(1, len(c | tk))
            worst = max(worst, j)
        scores.append(worst)
    return {"mean_max_jaccard": round(sum(scores) / len(scores), 4),
            "per_task": dict(zip([t["id"] for t in T.TASKS],
                                 [round(s, 3) for s in scores]))}


def main():
    out = {}
    for version in ("v1", "v2"):
        out[version] = {"adversarial": adversarial(version),
                        "bloat": bloat(version),
                        "confusability": confusability(version)}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "audit_results.json")
    json.dump(out, open(path, "w"), indent=1)
    for v, r in out.items():
        a, b, c = r["adversarial"], r["bloat"], r["confusability"]
        print(f"{v}: adversarial rejected {a['rejected']}/{a['n']} "
              f"(store mutated by bad calls: {a['store_mutated_by_bad_calls']}) | "
              f"task results {b['total_bytes']} bytes | "
              f"mean max confusability {c['mean_max_jaccard']}")
    print("wrote", path)


if __name__ == "__main__":
    main()
