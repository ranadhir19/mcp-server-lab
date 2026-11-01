# mcp-server-lab

Companion lab for The Architect's AI Workshop, Agent Series Ep. 1 —
**"Build an MCP Server a Model Can Actually Use."**

A language model never sees your server code. It sees tool names,
descriptions and JSON schemas — and nothing else. So an MCP server is
a *user interface for a language model*, and this lab measures what
that means: it exposes one notes store through two schema designs and
grades what happens when models try to use each one.

- `notes_server.py` — a real MCP server in pure Python stdlib
  (JSON-RPC 2.0 over stdio: `initialize`, `tools/list`, `tools/call`).
  `--schema v1` is deliberately ambiguous: three vague tools, a
  free-form action string, no required fields, bloated results, silent
  failures. `--schema v2` is the redesign: one verb per tool,
  descriptions that say when *not* to use the tool, strict schemas,
  compact results, structured errors.
- `mcp_client.py` — a minimal MCP client (spawns the server, performs
  the handshake, lists and calls tools).
- `tasks.py` — the fixed set of 16 user requests and the grading
  rubric (correct tool / wrong tool / malformed / task completed),
  applied identically to both versions.
- `run_trials.py` — the experiment. A chooser sees only the
  `tools/list` output and a request, answers with one JSON tool call,
  and the call is executed for real against a fresh seeded server.
- `audit.py` — deterministic, model-free measurements: an adversarial
  call suite, result-size totals, and a lexical confusability proxy
  (labelled a proxy — it measures shared words, not shared meaning).
- `validate.py` — the test harness. Pure stdlib; run it first.

## Run it

```bash
python3 validate.py          # 5 stages, must end with OVERALL: PASS
python3 audit.py             # deterministic audits -> audit_results.json
python3 run_trials.py --chooser oracle   # harness plumbing check only
```

Model trials (optional; needs `pip install llama-cpp-python` and a
GGUF instruct model):

```bash
python3 run_trials.py --chooser llm --model path/to/model.gguf \
    --out trials_model.json
```

## The experiment, and its criterion — stated before any run

**Question.** Does schema redesign (v1 → v2) change how often models
pick the wrong tool, produce malformed calls, and complete the task?

**Pre-stated success criterion.** Pooled across the models tested,
v2 counts as a win only if **wrong-tool calls fall by at least 30%
relative to v1** and **task completion rises**. Anything less and the
honest conclusion is the other one: that description quality is not
the lever — granularity or model capability is — and that is what gets
reported. The criterion lives here, in writing, before the trials run;
it does not move afterwards.

**Method notes.** Single-shot selection (one call per task, no
retries), temperature 0, fresh seeded store per task, results
inspected through the protocol itself. Models tested are small,
locally run open models — the point is the *comparison* between
schema versions on identical tasks, not a leaderboard. Small models
are also where schema quality should matter most: a frontier model
can often guess its way past a bad description; a small one cannot.

## What the deterministic audits already show

Run `audit.py` yourself: the loose v1 schema silently accepts all 10
adversarial calls (and two of them mutate the store); the strict v2
schema rejects all 10. Across the 16 ground-truth task calls, v1
returns roughly 5.5 times as many result bytes as v2. The lexical
confusability proxy, interestingly, scores v2 *worse* — its longer
descriptions share more vocabulary. Words are not meaning; that proxy
is kept in the lab as a standing warning against cheap metrics.
