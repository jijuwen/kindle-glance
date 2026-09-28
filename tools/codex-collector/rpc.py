"""Bounded stdio client for the official Codex app-server. No model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class RpcError(Exception):
    pass


class CodexRPC:
    def __init__(self, home: Path):
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        (home / "config.toml").write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")
        env = dict(os.environ, CODEX_HOME=str(home))
        self.proc = subprocess.Popen(
            [os.getenv("CODEX_BINARY", "/usr/local/bin/codex"), "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env, cwd=str(home), bufsize=1,
        )
        self.messages = queue.Queue()
        self.notifications = []
        self.next_id = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "kindle_usage_board", "version": "1.0.0"}}, 20)
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.messages.put(None)

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params=None, timeout=45):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RpcError("request timeout")
            if value is None:
                raise RpcError("app-server exited")
            if value.get("id") == request_id:
                if "error" in value:
                    raise RpcError(str(value["error"].get("message", "request failed")))
                return value.get("result", {})
            if "method" in value:
                self.notifications.append(value)

    def login_completed(self, login_id, timeout=1):
        values, self.notifications = self.notifications, []
        try:
            values.append(self.messages.get(timeout=timeout))
        except queue.Empty:
            pass
        for value in values:
            if value is None:
                raise RpcError("app-server exited")
            if value.get("method") == "account/login/completed" and value.get("params", {}).get("loginId") == login_id:
                return value["params"]
        return None

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream:
                stream.close()
