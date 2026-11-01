#!/usr/bin/env python3
"""notes_server.py — a real MCP server in pure Python stdlib.

Implements the Model Context Protocol over stdio (newline-delimited
JSON-RPC 2.0): initialize, notifications/initialized, ping, tools/list,
tools/call. The same notes store is exposed through two tool-schema
designs, selected with --schema:

  v1  Deliberately ambiguous. Three vaguely-named tools (note, notes,
      get), overlapping descriptions, no required fields, a free-form
      "action" string, loose argument checking, bloated results, and
      silent partial failures (an update to a missing id returns a
      success-shaped empty result). This is the "before" design.

  v2  Redesigned. One verb per tool (create_note, get_note,
      update_note, delete_note, list_notes, search_notes), each
      description says what the tool does AND when not to use it,
      strict schemas (required fields, additionalProperties: false),
      compact results, and structured errors: a missing id is an
      error, never a silent success.

Usage:  python3 notes_server.py --schema v1|v2
The store is seeded deterministically (see SEED) so every run of the
experiment starts from identical state.
"""
import argparse, json, sys

PROTOCOL_VERSION = "2025-06-18"

SEED = [
    {"id": "n1", "title": "Meeting notes",
     "body": "Weekly sync: roadmap, hiring, and the launch checklist."},
    {"id": "n2", "title": "Vendor paperwork",
     "body": "Invoice 1041 from the printer is still unpaid. Chase it."},
    {"id": "n3", "title": "Old draft",
     "body": "Scratch text that should have been thrown away."},
    {"id": "n4", "title": "Travel plans",
     "body": "Train to Chicago on Friday; the budget for the trip is 600 dollars."},
    {"id": "n5", "title": "Health",
     "body": "Dentist appointment on Thursday at 9 am. Bring the insurance card."},
    {"id": "n6", "title": "Reading list",
     "body": "A novel, two essays, and a paper about harbour engineering."},
]


class Store:
    def __init__(self):
        self.notes = {n["id"]: dict(n) for n in SEED}
        self.counter = 7  # next id n7, n8, ...

    def create(self, title, body):
        nid = f"n{self.counter}"; self.counter += 1
        self.notes[nid] = {"id": nid, "title": title, "body": body}
        return self.notes[nid]

    def get(self, nid):
        return self.notes.get(nid)

    def update(self, nid, title=None, body=None):
        n = self.notes.get(nid)
        if n is None:
            return None
        if title is not None:
            n["title"] = title
        if body is not None:
            n["body"] = body
        return n

    def delete(self, nid):
        return self.notes.pop(nid, None)

    def list_all(self):
        return [self.notes[k] for k in sorted(self.notes)]

    def search(self, query):
        q = query.lower()
        return [n for n in self.list_all()
                if q in n["title"].lower() or q in n["body"].lower()]


# ---------------------------------------------------------------- v1 tools
V1_TOOLS = [
    {"name": "note",
     "description": "Work with a note. Use this for notes.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string"},
         "id": {"type": "string"},
         "title": {"type": "string"},
         "text": {"type": "string"}}}},
    {"name": "notes",
     "description": "Handle notes in general.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "all": {"type": "boolean"}}}},
    {"name": "get",
     "description": "Get something from the store.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"},
         "title": {"type": "string"}}}},
]


def v1_call(store, name, args):
    """Loose dispatch: unknown actions fall through to a success-shaped
    empty result; missing ids are silent no-ops. Returns (text, is_error)."""
    args = args or {}
    if name == "note":
        action = str(args.get("action", "")).lower()
        if action in ("create", "add", "new"):
            n = store.create(args.get("title", ""), args.get("text", ""))
            return json.dumps({"ok": True, "note": n, "store_size": len(store.notes),
                               "all_ids": sorted(store.notes)}), False
        if action in ("update", "edit", "change"):
            n = store.update(args.get("id", ""), args.get("title"),
                             args.get("text"))
            # silent partial failure: success shape even when id is unknown
            return json.dumps({"ok": True, "note": n}), False
        if action in ("delete", "remove", "drop"):
            n = store.delete(args.get("id", ""))
            return json.dumps({"ok": True, "note": n}), False
        if action in ("read", "get", "show"):
            return json.dumps({"ok": True, "note": store.get(args.get("id", ""))}), False
        return json.dumps({"ok": True, "note": None}), False  # unknown action: silent
    if name == "notes":
        if args.get("query"):
            hits = store.search(args["query"])
            return json.dumps({"ok": True, "results": hits,
                               "store": store.list_all()}), False  # bloat: full store too
        return json.dumps({"ok": True, "results": store.list_all(),
                           "store": store.list_all()}), False
    if name == "get":
        if args.get("id"):
            return json.dumps({"ok": True, "note": store.get(args["id"])}), False
        if args.get("title"):
            for n in store.list_all():
                if n["title"] == args["title"]:
                    return json.dumps({"ok": True, "note": n}), False
        return json.dumps({"ok": True, "note": None}), False
    return json.dumps({"ok": False, "error": f"unknown tool {name}"}), True


# ---------------------------------------------------------------- v2 tools
def _strict(props, required):
    return {"type": "object", "properties": props,
            "required": required, "additionalProperties": False}


V2_TOOLS = [
    {"name": "create_note",
     "description": "Create a brand-new note with a title and a body. "
                    "Use only when the user wants a new note added; never "
                    "for changing or finding an existing note.",
     "inputSchema": _strict(
         {"title": {"type": "string"}, "body": {"type": "string"}},
         ["title", "body"])},
    {"name": "get_note",
     "description": "Read exactly one existing note by its id (for "
                    "example n2). Use when the id is known. To find notes "
                    "by topic or wording, use search_notes instead.",
     "inputSchema": _strict({"id": {"type": "string"}}, ["id"])},
    {"name": "update_note",
     "description": "Change the title and/or body of one existing note, "
                    "identified by its id. Only the fields you pass are "
                    "changed. The id must already exist.",
     "inputSchema": _strict(
         {"id": {"type": "string"}, "title": {"type": "string"},
          "body": {"type": "string"}}, ["id"])},
    {"name": "delete_note",
     "description": "Permanently delete one existing note by its id. "
                    "Use only when the user asks to remove a note.",
     "inputSchema": _strict({"id": {"type": "string"}}, ["id"])},
    {"name": "list_notes",
     "description": "List every note in the store (id and title only). "
                    "Use when the user asks to see all notes or asks how "
                    "many notes there are.",
     "inputSchema": _strict({}, [])},
    {"name": "search_notes",
     "description": "Find notes whose title or body contains a word or "
                    "phrase. Use when the user describes a note by its "
                    "content instead of giving an id.",
     "inputSchema": _strict({"query": {"type": "string"}}, ["query"])},
]


def _err(msg):
    return msg, True


def v2_call(store, name, args):
    args = args or {}
    tools = {t["name"]: t for t in V2_TOOLS}
    if name not in tools:
        return _err(f"unknown tool: {name}")
    schema = tools[name]["inputSchema"]
    for req in schema["required"]:
        if req not in args or args[req] is None:
            return _err(f"missing required argument: {req}")
    extra = set(args) - set(schema["properties"])
    if extra:
        return _err(f"unexpected argument(s): {', '.join(sorted(extra))}")
    for k, v in args.items():
        if schema["properties"][k].get("type") == "string" and not isinstance(v, str):
            return _err(f"argument {k} must be a string")
    if name == "create_note":
        n = store.create(args["title"], args["body"])
        return json.dumps({"id": n["id"], "title": n["title"]}), False
    if name == "get_note":
        n = store.get(args["id"])
        if n is None:
            return _err(f"no note with id {args['id']}")
        return json.dumps(n), False
    if name == "update_note":
        n = store.update(args["id"], args.get("title"), args.get("body"))
        if n is None:
            return _err(f"no note with id {args['id']}")
        return json.dumps({"id": n["id"], "title": n["title"]}), False
    if name == "delete_note":
        n = store.delete(args["id"])
        if n is None:
            return _err(f"no note with id {args['id']}")
        return json.dumps({"deleted": args["id"]}), False
    if name == "list_notes":
        return json.dumps([{ "id": n["id"], "title": n["title"]} for n in store.list_all()]), False
    if name == "search_notes":
        hits = store.search(args["query"])
        return json.dumps([{"id": n["id"], "title": n["title"]} for n in hits]), False
    return _err(f"unhandled tool {name}")


# ---------------------------------------------------------------- protocol
class Server:
    def __init__(self, schema):
        self.schema = schema
        self.store = Store()
        self.tools = V1_TOOLS if schema == "v1" else V2_TOOLS

    def handle(self, req):
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "notes-server", "version": self.schema}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"tools": self.tools}}
        if method == "tools/call":
            p = req.get("params") or {}
            name, args = p.get("name"), p.get("arguments") or {}
            call = v1_call if self.schema == "v1" else v2_call
            text, is_error = call(self.store, name, args)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error}}
        if rid is not None:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32601, "message": f"method not found: {method}"}}
        return None  # notification: no reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", choices=["v1", "v2"], required=True)
    a = ap.parse_args()
    srv = Server(a.schema)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = srv.handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
