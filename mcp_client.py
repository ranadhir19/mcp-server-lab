#!/usr/bin/env python3
"""mcp_client.py — a minimal MCP client (pure stdlib).

Spawns the notes server as a subprocess and speaks newline-delimited
JSON-RPC over its stdio: initialize -> notifications/initialized ->
tools/list / tools/call. Used by the experiment harness and the demo.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


class MCPClient:
    def __init__(self, schema, server_cmd=None):
        cmd = server_cmd or [sys.executable, os.path.join(HERE, "notes_server.py"),
                             "--schema", schema]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
        self._id = 0
        self.server_info = None

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed the pipe")
        return json.loads(line)

    def request(self, method, params=None):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        return self._read()

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self):
        r = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mcp-server-lab", "version": "1.0"}})
        self.server_info = r["result"]["serverInfo"]
        self.notify("notifications/initialized")
        return r["result"]

    def list_tools(self):
        return self.request("tools/list")["result"]["tools"]

    def call_tool(self, name, arguments):
        r = self.request("tools/call", {"name": name, "arguments": arguments})
        res = r["result"]
        text = res["content"][0]["text"] if res.get("content") else ""
        return text, bool(res.get("isError"))

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
