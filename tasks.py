#!/usr/bin/env python3
"""tasks.py — the fixed task set and the grading rubric.

Sixteen user requests against the seeded notes store. The same ground
truth applies to both schema versions; only the tool surface differs.

Rubric (applied identically to v1 and v2):
  correct_tool  the call addresses the task's intent through a tool
                that can perform it, with arguments that encode the
                right target (for v1 that includes a recognisable
                free-form "action" for the note tool).
  wrong_tool    the call's tool (or v1 action) belongs to a different
                intent, or the tool cannot perform the intent at all.
  malformed     no parseable call, or the arguments cannot encode the
                intent (missing target, empty action, invalid types).
  task_complete independent of the path: after the call, the world
                matches what the user asked for (checked against the
                store state and the returned text).
"""
import json

# intent -> v2 tool name
V2_TOOL = {"create": "create_note", "get": "get_note",
           "update": "update_note", "delete": "delete_note",
           "list": "list_notes", "search": "search_notes"}

# v1: intent -> (tool, acceptable actions or None)
V1_MAP = {"create": ("note", {"create", "add", "new"}),
          "get": ("get", None),
          "update": ("note", {"update", "edit", "change"}),
          "delete": ("note", {"delete", "remove", "drop"}),
          "list": ("notes", None),
          "search": ("notes", None)}
V1_GET_ACTIONS = {"read", "get", "show"}  # note tool may also read

TASKS = [
    {"id": "t01", "intent": "create",
     "text": "Add a new note titled 'Shopping list' with the body 'milk, eggs, bread'.",
     "title": "Shopping list", "body": "milk, eggs, bread"},
    {"id": "t02", "intent": "get",
     "text": "Read me the note with id n2.",
     "target": "n2", "needle": "Invoice 1041"},
    {"id": "t03", "intent": "search",
     "text": "Find notes that mention an invoice.",
     "query": "invoice", "hit": "n2"},
    {"id": "t04", "intent": "list",
     "text": "Show me all the notes in the store."},
    {"id": "t05", "intent": "update",
     "text": "Change the body of note n1 to 'Updated agenda: budget review'.",
     "target": "n1", "field": "body", "value": "Updated agenda: budget review"},
    {"id": "t06", "intent": "delete",
     "text": "Delete note n3.",
     "target": "n3"},
    {"id": "t07", "intent": "create",
     "text": "Create a note titled 'Invoice totals' whose body is 'Invoice 1042 totals 900 dollars'.",
     "title": "Invoice totals", "body": "Invoice 1042 totals 900 dollars"},
    {"id": "t08", "intent": "search",
     "text": "Which note is about the dentist appointment?",
     "query": "dentist", "hit": "n5"},
    {"id": "t09", "intent": "update",
     "text": "Rename note n4 to 'Travel plans v2'.",
     "target": "n4", "field": "title", "value": "Travel plans v2"},
    {"id": "t10", "intent": "list",
     "text": "How many notes are there in total?"},
    {"id": "t11", "intent": "get",
     "text": "Open note n5 for me.",
     "target": "n5", "needle": "Dentist appointment"},
    {"id": "t12", "intent": "update",
     "text": "Update note n2: its body should now be 'Call the plumber on Tuesday'.",
     "target": "n2", "field": "body", "value": "Call the plumber on Tuesday"},
    {"id": "t13", "intent": "search",
     "text": "Find anything about a budget.",
     "query": "budget", "hit": "n4"},
    {"id": "t14", "intent": "create",
     "text": "Make a new note called 'Budget 2027' with body 'Draft budget: 4000 dollars for travel'.",
     "title": "Budget 2027", "body": "Draft budget: 4000 dollars for travel"},
    {"id": "t15", "intent": "delete",
     "text": "Remove note n6.",
     "target": "n6"},
    {"id": "t16", "intent": "get",
     "text": "What does note n1 say?",
     "target": "n1", "needle": "Weekly sync"},
]

SEED_IDS = ["n1", "n2", "n3", "n4", "n5", "n6"]


def classify(task, version, tool, args):
    """Return 'correct_tool' | 'wrong_tool' | 'malformed' for one call."""
    if tool is None:
        return "malformed"
    args = args or {}
    intent = task["intent"]
    if version == "v2":
        if tool == V2_TOOL[intent]:
            return "correct_tool"
        return "wrong_tool"
    # v1
    want_tool, actions = V1_MAP[intent]
    if intent == "get" and tool == "note" and \
            str(args.get("action", "")).lower() in V1_GET_ACTIONS:
        return "correct_tool"
    if tool != want_tool:
        return "wrong_tool"
    if actions is not None:
        a = str(args.get("action", "")).lower()
        if a in actions:
            return "correct_tool"
        if a:
            return "wrong_tool"   # an action, but for a different intent
        return "malformed"        # note tool with no action at all
    if intent == "search":
        return "correct_tool" if args.get("query") else "malformed"
    if intent == "list":
        return "wrong_tool" if args.get("query") else "correct_tool"
    return "correct_tool"


def completed(task, args, result_text, state):
    """state: list of full note dicts after the call."""
    intent = task["intent"]
    if intent == "create":
        return any(n["title"] == task["title"] and n["body"] == task["body"]
                   for n in state)
    if intent == "get":
        return task["needle"] in (result_text or "")
    if intent == "search":
        query_ok = task["query"] in str((args or {}).get("query", "")).lower()
        if not query_ok:
            return False
        try:
            payload = json.loads(result_text)
        except Exception:
            return False
        hits = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(hits, list):
            return False
        return any(isinstance(h, dict) and h.get("id") == task["hit"]
                   for h in hits)
    if intent == "list":
        return all(sid in (result_text or "") for sid in SEED_IDS)
    if intent == "update":
        n = next((x for x in state if x["id"] == task["target"]), None)
        return n is not None and n[task["field"]] == task["value"]
    if intent == "delete":
        return all(x["id"] != task["target"] for x in state)
    return False
