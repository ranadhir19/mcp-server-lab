# mcp-server-lab

Companion lab for The Architect's AI Workshop, Agent Series Ep. 1 —
**"Build an MCP Server a Model Can Actually Use."**

A language model never sees your server code. It sees tool names,
descriptions and JSON schemas — and nothing else. So an MCP server is
a *user interface for a language model*, and this lab measures what
that means: it exposes one notes store through two schema designs and
grades what happens when models try to use each one.

**Listed in the [HOL Registry](https://hol.org/plugins)** — owner-verified
listing (catalogue PR merged 2026-11-04).

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

## Installation

The server has no dependencies beyond Python itself — the server,
the client and the harness are pure standard library (JSON-RPC 2.0
over stdio). Tested with Python 3.12.

```bash
git clone https://github.com/ranadhir19/mcp-server-lab.git
cd mcp-server-lab
python3 validate.py   # self-check: must end with OVERALL: PASS (5/5 stages)
```

That is the whole install: nothing to build, no package to install.
(In fact the only command in this lab that needs a third-party
package is the optional model-trial runner — see "Run it".)

## MCP configuration

An MCP client launches the server over stdio. Point the client at
`notes_server.py` with `--schema v2` to get the strict design: six
tools (`create_note`, `get_note`, `update_note`, `delete_note`,
`list_notes`, `search_notes`), required fields enforced,
`additionalProperties: false`, and structured errors instead of
silent failures. For any client that takes the standard
`mcpServers` JSON (Claude Desktop, Claude Code, Cursor and others):

```json
{
  "mcpServers": {
    "notes-strict": {
      "command": "python3",
      "args": ["/absolute/path/to/mcp-server-lab/notes_server.py", "--schema", "v2"]
    }
  }
}
```

Replace `/absolute/path/to/mcp-server-lab` with the directory you
cloned into. With Claude Code, the same registration is one command:

```bash
claude mcp add notes-strict -- python3 /absolute/path/to/mcp-server-lab/notes_server.py --schema v2
```

Then ask the model to list, create, search, update or delete notes.
Two things to know: the store starts from the same six seeded notes
(n1–n6) on every launch, and state is in memory only — it resets
when the server restarts, which is deliberate for a teaching lab.
(`--schema v1` swaps in the deliberately loose design, so you can
watch the same client's calls fail against it.)

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
adversarial calls (and three of them mutate the store); the strict v2
schema rejects all 10. Across the 16 ground-truth task calls, v1
returns roughly 5.5 times as many result bytes as v2. The lexical
confusability proxy, interestingly, scores v2 *worse* — its longer
descriptions share more vocabulary. Words are not meaning; that proxy
is kept in the lab as a standing warning against cheap metrics.
