#!/usr/bin/env python3
"""run_trials.py — the tool-selection experiment.

For each schema version and each task, a chooser sees ONLY what a model
would see — the tools/list response and the user's request — and must
answer with one JSON tool call. The call is then executed for real
against a fresh server (fresh seeded store), the resulting state is
inspected through the protocol, and the call is graded with the rubric
in tasks.py.

Choosers:
  llm     a local GGUF model via llama-cpp-python (optional dependency;
          see README). This is the chooser used for published numbers.
  oracle  ground-truth calls. NOT a model — used only to sanity-check
          the harness and to measure result sizes in audit.py. Oracle
          rows are labelled ORACLE wherever they appear and are never
          mixed into model results.

Usage:
  python3 run_trials.py --chooser llm --model qwen1.5b.gguf \
      [--tasks t01,t02] [--out results.json]
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MCPClient
import tasks as T

SYSTEM = ("You are an AI agent. You have access to the tools listed "
          "below. For the user's request, respond with exactly one JSON "
          "object of the form {\"name\": \"<tool name>\", \"arguments\": "
          "{...}} and nothing else — no explanation, no markdown.")


def inspect_state(client, version):
    """Full store contents, read back through the protocol itself."""
    if version == "v1":
        text, _ = client.call_tool("notes", {})
        return json.loads(text)["results"]
    text, _ = client.call_tool("list_notes", {})
    out = []
    for item in json.loads(text):
        t, err = client.call_tool("get_note", {"id": item["id"]})
        if not err:
            out.append(json.loads(t))
    return out


def oracle_call(task, version):
    """The ground-truth call for a task (harness plumbing only)."""
    i = task["intent"]
    if version == "v2":
        name = T.V2_TOOL[i]
        if i == "create":
            args = {"title": task["title"], "body": task["body"]}
        elif i in ("get", "delete"):
            args = {"id": task["target"]}
        elif i == "update":
            args = {"id": task["target"], task["field"]: task["value"]}
        elif i == "search":
            args = {"query": task["query"]}
        else:
            args = {}
        return name, args
    # v1
    if i == "create":
        return "note", {"action": "create", "title": task["title"],
                        "text": task["body"]}
    if i == "get":
        return "get", {"id": task["target"]}
    if i == "update":
        key = "title" if task["field"] == "title" else "text"
        return "note", {"action": "update", "id": task["target"],
                        key: task["value"]}
    if i == "delete":
        return "note", {"action": "delete", "id": task["target"]}
    if i == "search":
        return "notes", {"query": task["query"]}
    return "notes", {}


def parse_call(raw):
    """Extract the first JSON object with a 'name' from raw model text."""
    if not raw:
        return None, None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None, None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None, None
    if not isinstance(obj, dict) or "name" not in obj:
        return None, None
    return obj.get("name"), obj.get("arguments") or {}


class LLMChooser:
    def __init__(self, model_path):
        from llama_cpp import Llama
        # n_threads=1 is deliberate: on a contended shared host, llama.cpp's
        # multi-thread barrier synchronisation collapses throughput
        # (measured: a 459-token call took over 10 minutes at 4 threads vs
        # 8 seconds at 1 thread, same machine, same load). Thread count is
        # an inference-runtime parameter; it does not change the prompt,
        # the sampling (temperature 0, fixed seed) or the grading.
        threads = int(os.environ.get("MCP_LAB_THREADS", "1"))
        # use_mlock: on this shared host the page cache is thrashed by other
        # tenants; without mlock, generation stalls in disk wait (main
        # thread observed in D state) as weight pages are evicted between
        # tokens. Locking the weights resident removes that failure mode.
        # Runtime parameter only; prompts/sampling/grading unchanged.
        mlock = os.environ.get("MCP_LAB_MLOCK", "1") == "1"
        self.llm = Llama(model_path=model_path, n_ctx=4096,
                         n_threads=threads, use_mlock=mlock, verbose=False)
        self.model_name = os.path.basename(model_path)

    def choose(self, tools, task_text):
        user = ("Tools:\n" + json.dumps(tools, indent=1) +
                "\n\nUser request: " + task_text)
        out = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            temperature=0.0, seed=1234, max_tokens=160)
        return out["choices"][0]["message"]["content"]


def run(chooser_name, model_path=None, task_ids=None, out_path=None):
    chooser = None
    if chooser_name == "llm":
        chooser = LLMChooser(model_path)
        label = chooser.model_name
    else:
        label = "ORACLE"
    rows = []
    if out_path and os.path.exists(out_path):
        try:
            prev = json.load(open(out_path))
            if prev.get("chooser") == label:
                rows = prev.get("rows", [])
                print(f"resuming: {len(rows)} rows already in {out_path}",
                      flush=True)
        except Exception:
            rows = []
    done_pairs = {(r["version"], r["task"]) for r in rows}
    for version in ("v1", "v2"):
        probe = MCPClient(version)
        probe.initialize()
        tools = probe.list_tools()
        probe.close()
        for task in T.TASKS:
            if task_ids and task["id"] not in task_ids:
                continue
            if (version, task["id"]) in done_pairs:
                print(f"{label} {version} {task['id']} -> skip (done)",
                      flush=True)
                continue
            if chooser_name == "oracle":
                name, args = oracle_call(task, version)
                raw = json.dumps({"name": name, "arguments": args})
            else:
                raw = chooser.choose(tools, task["text"])
                name, args = parse_call(raw)
            client = MCPClient(version)
            client.initialize()
            result_text, is_error = "", False
            if name is not None:
                try:
                    result_text, is_error = client.call_tool(name, args)
                except Exception as e:
                    result_text, is_error = f"client error: {e}", True
            state = inspect_state(client, version)
            client.close()
            cls = T.classify(task, version, name, args)
            if name is not None and is_error and cls == "correct_tool":
                cls = "malformed"  # right tool, arguments the server rejects
            done = T.completed(task, args, result_text, state)
            rows.append({"task": task["id"], "intent": task["intent"],
                         "version": version, "chooser": label,
                         "tool": name, "args": args, "class": cls,
                         "is_error": is_error, "completed": done,
                         "raw": (raw or "")[:300]})
            print(f"{label} {version} {task['id']} -> {name} "
                  f"[{cls}] completed={done}", flush=True)
            if out_path:
                # Incremental persistence: a killed/OOMed run keeps every
                # completed call on disk (production-hardening only; the
                # protocol and grading are unchanged).
                s = {}
                for v in ("v1", "v2"):
                    sub = [r for r in rows if r["version"] == v]
                    if sub:
                        s[v] = {
                            "n": len(sub),
                            "correct_tool": sum(r["class"] == "correct_tool"
                                                for r in sub),
                            "wrong_tool": sum(r["class"] == "wrong_tool"
                                              for r in sub),
                            "malformed": sum(r["class"] == "malformed"
                                             for r in sub),
                            "completed": sum(r["completed"] for r in sub)}
                json.dump({"chooser": label, "summary": s, "rows": rows},
                          open(out_path, "w"), indent=1)
    summary = {}
    for version in ("v1", "v2"):
        sub = [r for r in rows if r["version"] == version]
        if not sub:
            continue
        summary[version] = {
            "n": len(sub),
            "correct_tool": sum(r["class"] == "correct_tool" for r in sub),
            "wrong_tool": sum(r["class"] == "wrong_tool" for r in sub),
            "malformed": sum(r["class"] == "malformed" for r in sub),
            "completed": sum(r["completed"] for r in sub)}
    result = {"chooser": label, "summary": summary, "rows": rows}
    if out_path:
        json.dump(result, open(out_path, "w"), indent=1)
    print(json.dumps(summary, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chooser", choices=["llm", "oracle"], default="oracle")
    ap.add_argument("--model")
    ap.add_argument("--tasks")
    ap.add_argument("--out")
    a = ap.parse_args()
    run(a.chooser, a.model,
        set(a.tasks.split(",")) if a.tasks else None, a.out)
