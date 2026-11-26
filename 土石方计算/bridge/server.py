"""本机 HTTP 会话、命令确认与认证，不依赖界面线程。"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from uuid import uuid4


class BridgeError(ValueError):
    """插件消息不满足当前会话或任务合同。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _windows_resource_path(path, *, for_io=True):
    """只统一普通盘符、UNC 及其扩展写法，不接纳其他设备命名空间。"""
    path = Path(path)
    if os.name != "nt":
        return path
    value = str(path)
    if value.startswith("\\\\.\\"):
        raise BridgeError("资源路径使用了不支持的设备命名空间")
    if value.startswith("\\\\?\\"):
        ordinary = value[4:]
        if ordinary.upper().startswith("UNC\\"):
            unc_parts = ordinary[4:].split("\\")
            if len(unc_parts) < 2 or not unc_parts[0] or not unc_parts[1]:
                raise BridgeError("资源路径使用了不支持的设备命名空间")
            ordinary = "\\\\" + ordinary[4:]
        elif not (len(ordinary) >= 3 and ordinary[0] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  and ordinary[1:3] == ":\\"):
            raise BridgeError("资源路径使用了不支持的设备命名空间")
        path = Path(ordinary)
        if not path.is_absolute():
            raise BridgeError("资源路径使用了不支持的设备命名空间")
        value = str(path)
    if (for_io and path.is_absolute()
            and (len(value) >= 260 or len(str(path.parent)) >= 248)):
        return Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\")
                    else "\\\\?\\" + value)
    return path


def atomic_json(path, payload):
    """写完并刷新临时文件后原子替换，避免读取半套元数据。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RhinoBridge:
    """一项工程一个会话，插件拉取并幂等处理命令。"""

    def __init__(self, project_id, resource_root, receiver, *, clock=time.monotonic):
        self.project_id = str(project_id)
        self.resource_root = _windows_resource_path(resource_root).resolve()
        self.receiver = receiver
        self.session_id = uuid4().hex
        self._token = secrets.token_urlsafe(32)
        self._clock = clock
        self._lock = threading.RLock()
        self._server = None
        self._thread = None
        self._commands = []
        self._sequence = 0
        self._client = None
        self._last_seen = None
        self.discovery_path = self.resource_root / "session" / "connection.json"

    @property
    def url(self):
        return "" if self._server is None else f"http://127.0.0.1:{self._server.server_port}"

    @property
    def client(self):
        with self._lock:
            return copy.deepcopy(self._client)

    @property
    def connected(self):
        with self._lock:
            return bool(self._client and self._last_seen is not None
                        and self._clock() - self._last_seen < 45)

    def start(self):
        if self._server is not None:
            return str(self.discovery_path)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # 不记录带有认证凭据的请求或参数。
                return

            def _reply(self, status, data):
                raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _handle(self):
                header = self.headers.get("Authorization", "")
                if not hmac.compare_digest(header, "Bearer " + owner._token):
                    self._reply(401, {"error": "未通过本机会话认证"})
                    return
                try:
                    parsed = urlparse(self.path)
                    payload = {}
                    if self.command == "POST":
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 <= length <= 32 * 1024 * 1024:
                            raise BridgeError("消息超出允许大小", 413)
                        if "application/json" not in self.headers.get("Content-Type", ""):
                            raise BridgeError("请求必须是 JSON", 415)
                        payload = json.loads(self.rfile.read(length).decode("utf-8"),
                                             parse_constant=lambda value: (_ for _ in ()).throw(
                                                 ValueError("JSON 含非有限数值")))
                        if not isinstance(payload, dict):
                            raise BridgeError("请求必须是 JSON 对象")
                    result = owner.dispatch(self.command, parsed.path, payload, parse_qs(parsed.query))
                    self._reply(200, result)
                except BridgeError as exc:
                    self._reply(exc.status, {"error": str(exc)})
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    self._reply(400, {"error": str(exc)})
                except Exception as exc:
                    self._reply(500, {"error": "本机处理失败：" + str(exc)})

            do_GET = _handle
            do_POST = _handle

        self.resource_root.mkdir(parents=True, exist_ok=True)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="RhinoBridge", daemon=True)
        self._thread.start()
        atomic_json(self.discovery_path, {
            "protocol_version": "1.0", "url": self.url, "token": self._token,
            "session_id": self.session_id, "project_id": self.project_id,
            "resource_root": str(self.resource_root),
        })
        return str(self.discovery_path)

    def close(self):
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            self._client = None
        if self.discovery_path.exists():
            try:
                content = json.loads(self.discovery_path.read_text(encoding="utf-8"))
                if content.get("session_id") == self.session_id:
                    self.discovery_path.unlink()
            except (OSError, ValueError):
                pass

    def enqueue(self, command_type, payload):
        with self._lock:
            self._sequence += 1
            item = {"command_id": uuid4().hex, "sequence": self._sequence,
                    "type": str(command_type), "payload": copy.deepcopy(payload),
                    "acknowledged": False}
            self._commands.append(item)
            return item["command_id"]

    def discard(self, *, job_id=None, types=None):
        with self._lock:
            for item in self._commands:
                if ((job_id is None or item["payload"].get("job_id") == job_id)
                        and (types is None or item["type"] in types)):
                    item["acknowledged"] = True

    def resource_path(self, value, *, must_exist=True):
        """验证传输资源属于当前工程，阻止越界及链接跳转。"""
        path = _windows_resource_path(value, for_io=False)
        if not path.is_absolute():
            path = self.resource_root / path
        path = _windows_resource_path(path).resolve()
        if not _windows_resource_path(path, for_io=False).is_relative_to(
                _windows_resource_path(self.resource_root, for_io=False)):
            raise BridgeError("资源不属于当前工程")
        if must_exist and not path.is_file():
            raise BridgeError("工程资源不存在：" + str(path))
        return path

    def dispatch(self, method, path, payload, query=None):
        query = query or {}
        if path == "/v1/hello" and method == "POST":
            if not payload.get("client_id") or not payload.get("document_id"):
                raise BridgeError("缺少插件或文档身份")
            if payload.get("protocol_version", "1.0") != "1.0":
                raise BridgeError("Rhino 插件与主程序协议版本不兼容", 409)
            with self._lock:
                old_client = self._client
                old_last_seen = self._last_seen
                if (old_client and old_client.get("exclusive_session")
                        and old_client.get("client_id") != payload["client_id"]
                        and self._last_seen is not None and self._clock() - self._last_seen < 45):
                    raise BridgeError("当前工程已连接另一个 Rhino 工作台，请先在原工作台断开", 409)
                self._client = copy.deepcopy(payload)
                self._last_seen = self._clock()
            try:
                self.receiver("hello", payload)
            except Exception:
                with self._lock:
                    self._client = old_client
                    self._last_seen = old_last_seen
                raise
            return {"session_id": self.session_id, "project_id": self.project_id,
                    "protocol_version": "1.0"}
        if path == "/v1/status" and method == "GET":
            return self.receiver("status", {})
        client_id = payload.get("client_id") or (query.get("client_id") or [None])[0]
        with self._lock:
            if self._client is None:
                raise BridgeError("插件尚未绑定工程文档", 409)
            if client_id is not None and client_id != self._client["client_id"]:
                raise BridgeError("插件身份与当前会话不符", 409)
            if path == "/v1/disconnect" and method == "POST":
                if client_id != self._client["client_id"]:
                    raise BridgeError("断开请求缺少当前客户端身份", 409)
                self._client = None
                self._last_seen = None
                disconnected = True
            else:
                disconnected = False
                self._last_seen = self._clock()
            if path == "/v1/commands" and method == "GET":
                return {"commands": [
                    {k: copy.deepcopy(v) for k, v in item.items() if k != "acknowledged"}
                    for item in self._commands if not item["acknowledged"]
                ]}
            if path == "/v1/ack" and method == "POST":
                for item in self._commands:
                    if item["command_id"] == payload.get("command_id"):
                        item["acknowledged"] = True
                        return {"ok": True}
                raise BridgeError("命令不存在", 404)
        if disconnected:
            return self.receiver("disconnect", payload) or {"ok": True}
        routes = {
            "/v1/terrain": "terrain", "/v1/progress": "progress",
            "/v1/result": "result", "/v1/committed": "committed",
            "/v1/failure": "failure", "/v1/event": "event",
            "/v1/action": "action",
        }
        if method != "POST" or path not in routes:
            raise BridgeError("未知协议操作", 404)
        return self.receiver(routes[path], payload) or {"ok": True}
