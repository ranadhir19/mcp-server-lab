#!/usr/bin/env python3
"""validate.py — the lab's test harness. Pure stdlib, no model needed.

Stages:
  1. Protocol conformance: initialize handshake, tools/list shape,
     ping, unknown-method error — for both schema versions.
  2. Store correctness through the protocol (v2): the seeded store,
     CRUD round-trips, search/list contents.
  3. Grading plumbing: oracle (ground-truth) calls for all 16 tasks on
     both versions classify as correct_tool and complete. This tests
     the harness, NOT any model.
  4. Audit: the deterministic audits execute and return well-formed
     numbers; design-intent check that the strict schema rejects more
     adversarial calls than the loose one.
  5. Response parsing: run_trials.parse_call on representative raw
     model outputs (clean JSON, prose-wrapped JSON, garbage).

Every stage prints PASS or FAIL; the harness exits non-zero on any
failure and prints an OVERALL line at the end.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MCPClient
import tasks as T
import run_trials, audit

FAILURES = []


def stage(name, fn):
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        FAILURES.append(name)
        print(f"FAIL  {name}: {e}")


def s1_protocol():
    for version, ntools in (("v1", 3), ("v2", 6)):
        c = MCPClient(version)
        info = c.initialize()
        assert info["serverInfo"]["name"] == "notes-server", info
        assert info["protocolVersion"], info
        tools = c.list_tools()
        assert len(tools) == ntools, (version, len(tools))
        for t in tools:
            assert t["name"] and t["description"] and "inputSchema" in t, t
        r = c.request("ping")
        assert r["result"] == {}, r
        r = c.request("no/such/method")
        assert "error" in r, r
        c.close()


def s2_store():
    c = MCPClient("v2"); c.initialize()
    state = run_trials.inspect_state(c, "v2")
    assert [n["id"] for n in state] == T.SEED_IDS, state
    text, err = c.call_tool("create_note", {"title": "T", "body": "B"})
    assert not err and json.loads(text)["id"] == "n7", text
    text, err = c.call_tool("get_note", {"id": "n7"})
    assert not err and json.loads(text)["body"] == "B", text
    text, err = c.call_tool("update_note", {"id": "n7", "body": "B2"})
    assert not err, text
    text, err = c.call_tool("search_notes", {"query": "invoice"})
    assert not err and [h["id"] for h in json.loads(text)] == ["n2"], text
    text, err = c.call_tool("delete_note", {"id": "n7"})
    assert not err and json.loads(text)["deleted"] == "n7", text
    text, err = c.call_tool("get_note", {"id": "n7"})
    assert err, "deleted note must read as an error"
    c.close()


def s3_grading():
    res = run_trials.run("oracle")
    for version in ("v1", "v2"):
        s = res["summary"][version]
        assert s["n"] == 16, s
        assert s["correct_tool"] == 16, (version, s)
        assert s["completed"] == 16, (version, s)


def s4_audit():
    for version in ("v1", "v2"):
        a = audit.adversarial(version)
        assert a["n"] == 10 and 0 <= a["rejected"] <= 10, a
        b = audit.bloat(version)
        assert b["total_bytes"] > 0 and len(b["per_task"]) == 16, b
        cf = audit.confusability(version)
        assert 0.0 <= cf["mean_max_jaccard"] <= 1.0, cf
    a1, a2 = audit.adversarial("v1"), audit.adversarial("v2")
    assert a2["rejected"] > a1["rejected"], (a1["rejected"], a2["rejected"])


def s5_parse():
    name, args = run_trials.parse_call('{"name": "get_note", "arguments": {"id": "n2"}}')
    assert name == "get_note" and args == {"id": "n2"}, (name, args)
    name, _ = run_trials.parse_call('Sure! {"name": "list_notes", "arguments": {}} done')
    assert name == "list_notes", name
    name, _ = run_trials.parse_call("I would call the tool now.")
    assert name is None, name
    name, _ = run_trials.parse_call("")
    assert name is None, name


if __name__ == "__main__":
    stage("1 protocol conformance (v1+v2)", s1_protocol)
    stage("2 store correctness via protocol (v2)", s2_store)
    stage("3 grading plumbing — oracle 16/16 both versions", s3_grading)
    stage("4 deterministic audits execute; strict rejects more", s4_audit)
    stage("5 response parsing", s5_parse)
    if FAILURES:
        print("OVERALL: FAIL", FAILURES)
        sys.exit(1)
    print("OVERALL: PASS (5/5 stages)")
