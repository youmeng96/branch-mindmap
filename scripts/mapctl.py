#!/usr/bin/env python3
"""Create, edit, render, validate, and serve a local Codex branch map."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = 1
KINDS = {"goal", "step", "decision", "branch", "artifact", "risk"}
STATUSES = {"todo", "active", "done", "blocked", "rejected"}
ORIGINS = {"codex", "editor"}
SKILL_ROOT = Path(__file__).resolve().parents[1]
EDITOR_TEMPLATE = SKILL_ROOT / "assets" / "map_editor.html"
MAX_BODY_BYTES = 2 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_event(event_type: str, message: str, revision: int, **extra: Any) -> dict[str, Any]:
    event = {
        "id": f"evt-{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "message": message,
        "timestamp": utc_now(),
        "revision": revision,
    }
    event.update(extra)
    return event


def make_node(
    node_id: str,
    title: str,
    *,
    parent_id: str | None = None,
    summary: str = "",
    kind: str = "step",
    status: str = "todo",
    origin: str = "codex",
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "id": node_id,
        "parent_id": parent_id,
        "title": title,
        "summary": summary,
        "kind": kind,
        "status": status,
        "origin": origin,
        "artifacts": artifacts or [],
        "created_at": now,
        "updated_at": now,
    }


def next_node_id(nodes: list[dict[str, Any]]) -> str:
    highest = 0
    for node in nodes:
        node_id = str(node.get("id", ""))
        if node_id.startswith("n-") and node_id[2:].isdigit():
            highest = max(highest, int(node_id[2:]))
    return f"n-{highest + 1:04d}"


@contextlib.contextmanager
def file_lock(map_path: str | Path):
    """Serialize read-modify-write operations across CLI and server processes."""
    lock_dir = Path(map_path).resolve().parent / ".map.lock.d"
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 20.0
    while True:
        try:
            os.mkdir(lock_dir)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
                if age > 120:
                    os.rmdir(lock_dir)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for map lock: {lock_dir}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.rmdir(lock_dir)
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_map(path: str | Path) -> dict[str, Any]:
    map_path = Path(path).resolve()
    try:
        with map_path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"map file not found: {map_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {map_path}: {exc}") from exc

    errors = validate_map(data)
    if errors:
        raise ValueError("invalid map:\n- " + "\n- ".join(errors))
    return data


def save_map(path: str | Path, data: dict[str, Any], *, append_event_file: bool = True) -> None:
    map_path = Path(path).resolve()
    data["task"]["updated_at"] = utc_now()
    atomic_write_json(map_path, data)
    if append_event_file and data.get("events"):
        append_events(map_path.parent / "events.jsonl", [data["events"][-1]])


def validate_map(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(data.get("task_id"), str) or not data.get("task_id", "").strip():
        errors.append("task_id must be a non-empty string")
    revision = data.get("revision")
    if not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer >= 1")

    task = data.get("task")
    if not isinstance(task, dict):
        errors.append("task must be an object")
    else:
        for key in ("title", "status", "created_at", "updated_at"):
            if not isinstance(task.get(key), str):
                errors.append(f"task.{key} must be a string")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty array")
        return errors

    ids: set[str] = set()
    parent_ids: set[str | None] = set()
    normalized: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        normalized.append(node)
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            errors.append(f"nodes[{index}].id must be a non-empty string")
            continue
        if node_id in ids:
            errors.append(f"duplicate node id: {node_id}")
        ids.add(node_id)
        parent_id = node.get("parent_id")
        if parent_id is not None and not isinstance(parent_id, str):
            errors.append(f"node {node_id}: parent_id must be a string or null")
        parent_ids.add(parent_id)
        if not isinstance(node.get("title"), str) or not node.get("title", "").strip():
            errors.append(f"node {node_id}: title must be a non-empty string")
        if not isinstance(node.get("summary", ""), str):
            errors.append(f"node {node_id}: summary must be a string")
        if node.get("kind") not in KINDS:
            errors.append(f"node {node_id}: invalid kind {node.get('kind')!r}")
        if node.get("status") not in STATUSES:
            errors.append(f"node {node_id}: invalid status {node.get('status')!r}")
        if node.get("origin") not in ORIGINS:
            errors.append(f"node {node_id}: invalid origin {node.get('origin')!r}")
        artifacts = node.get("artifacts", [])
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            errors.append(f"node {node_id}: artifacts must be an array of strings")
        for key in ("created_at", "updated_at"):
            if not isinstance(node.get(key), str):
                errors.append(f"node {node_id}: {key} must be a string")

    for parent_id in parent_ids:
        if parent_id is not None and parent_id not in ids:
            errors.append(f"parent_id does not exist: {parent_id}")

    parent_by_id = {
        node.get("id"): node.get("parent_id")
        for node in normalized
        if isinstance(node.get("id"), str)
    }
    for node_id in ids:
        seen: set[str] = set()
        cursor: str | None = node_id
        while cursor is not None:
            if cursor in seen:
                errors.append(f"cycle detected at node {node_id}")
                break
            seen.add(cursor)
            cursor = parent_by_id.get(cursor)

    checkpoints = data.get("checkpoints")
    if not isinstance(checkpoints, list):
        errors.append("checkpoints must be an array")
    events = data.get("events")
    if not isinstance(events, list):
        errors.append("events must be an array")
    return errors


def map_paths(map_path: str | Path) -> tuple[Path, Path, Path]:
    path = Path(map_path).resolve()
    return path.parent / "mindmap.html", path.parent / "mindmap.md", path.parent / "events.jsonl"


def escape_mermaid(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
    )


def render_mermaid(data: dict[str, Any]) -> str:
    lines = ["# Branch Map", "", "```mermaid", "graph LR"]
    node_ids = {node["id"] for node in data["nodes"]}
    for node in data["nodes"]:
        safe_id = node["id"].replace("-", "_")
        label = escape_mermaid(node["title"])
        lines.append(f'  {safe_id}["{label}"]')
    for node in data["nodes"]:
        if node.get("parent_id") in node_ids:
            parent = node["parent_id"].replace("-", "_")
            child = node["id"].replace("-", "_")
            lines.append(f"  {parent} --> {child}")
    for status in sorted(STATUSES):
        matching = [n["id"].replace("-", "_") for n in data["nodes"] if n["status"] == status]
        if matching:
            lines.append(f"  classDef {status} {status_style(status)};")
            lines.append(f"  class {','.join(matching)} {status};")
    lines.extend(["```", ""])
    return "\n".join(lines)


def status_style(status: str) -> str:
    styles = {
        "todo": "fill:#e2e8f0,stroke:#64748b,color:#0f172a",
        "active": "fill:#dbeafe,stroke:#2563eb,color:#172554",
        "done": "fill:#dcfce7,stroke:#16a34a,color:#052e16",
        "blocked": "fill:#fee2e2,stroke:#dc2626,color:#450a0a",
        "rejected": "fill:#f3e8ff,stroke:#9333ea,color:#3b0764",
    }
    return styles.get(status, styles["todo"])


def render_html(data: dict[str, Any]) -> str:
    if not EDITOR_TEMPLATE.exists():
        raise FileNotFoundError(f"editor template not found: {EDITOR_TEMPLATE}")
    template = EDITOR_TEMPLATE.read_text(encoding="utf-8")
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace("__EMBEDDED_MAP__", embedded)


def render_map(map_path: str | Path) -> tuple[Path, Path]:
    path = Path(map_path).resolve()
    data = load_map(path)
    html_path, md_path, _ = map_paths(path)
    atomic_write_text(html_path, render_html(data))
    atomic_write_text(md_path, render_mermaid(data))
    return html_path, md_path


def bump_and_event(data: dict[str, Any], event_type: str, message: str, **extra: Any) -> None:
    data["revision"] += 1
    event = make_event(event_type, message, data["revision"], **extra)
    data["events"].append(event)


def command_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    task_id = f"task-{stamp}-{uuid.uuid4().hex[:4]}"
    folder = workspace / ".codex-mindmap" / task_id
    folder.mkdir(parents=True, exist_ok=False)
    map_path = folder / "map.json"
    now = utc_now()
    root = make_node(
        "n-0001",
        args.task,
        summary=args.goal or "",
        kind="goal",
        status="active",
    )
    data = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "revision": 1,
        "task": {
            "id": task_id,
            "title": args.task,
            "goal": args.goal or "",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "nodes": [root],
        "checkpoints": [],
        "events": [make_event("init", f"Initialized map for: {args.task}", 1)],
    }
    save_map(map_path, data)
    render_map(map_path)
    print(json.dumps({"task_id": task_id, "map": str(map_path)}, ensure_ascii=False))
    return 0


def require_revision(data: dict[str, Any], expected_revision: int, command: str) -> None:
    if data["revision"] != expected_revision:
        raise ValueError(
            f"{command} rejected: expected revision {expected_revision}, current revision is {data['revision']}. Reload the map and retry."
        )


def command_add(args: argparse.Namespace) -> int:
    map_path = Path(args.map).resolve()
    with file_lock(map_path):
        data = load_map(map_path)
        require_revision(data, args.expected_revision, "add")
        if args.parent not in {node["id"] for node in data["nodes"]}:
            raise ValueError(f"parent node not found: {args.parent}")
        node_id = next_node_id(data["nodes"])
        node = make_node(
            node_id,
            args.title,
            parent_id=args.parent,
            summary=args.summary or "",
            kind=args.kind,
            status=args.status,
            origin=args.origin,
            artifacts=getattr(args, "artifacts", None),
        )
        data["nodes"].append(node)
        bump_and_event(data, "node_added", f"Added {node_id}: {args.title}", node_id=node_id)
        save_map(map_path, data)
        render_map(map_path)
    print(json.dumps(node, ensure_ascii=False))
    return 0


def command_update(args: argparse.Namespace) -> int:
    map_path = Path(args.map).resolve()
    with file_lock(map_path):
        data = load_map(map_path)
        require_revision(data, args.expected_revision, "update")
        node = next((item for item in data["nodes"] if item["id"] == args.node), None)
        if node is None:
            raise ValueError(f"node not found: {args.node}")

        changed: dict[str, Any] = {}
        for key in ("title", "summary", "kind", "status"):
            value = getattr(args, key, None)
            if value is not None and node.get(key) != value:
                node[key] = value
                changed[key] = value
        artifacts = getattr(args, "artifacts", None)
        if artifacts is not None and node.get("artifacts", []) != artifacts:
            node["artifacts"] = artifacts
            changed["artifacts"] = artifacts
        if not changed:
            print(json.dumps(node, ensure_ascii=False))
            return 0
        if node.get("origin") == "editor" and args.origin == "codex" and not getattr(args, "allow_editor_overwrite", False):
            raise ValueError(
                f"node {args.node} was edited by the user; reload and retry with --allow-editor-overwrite only after explicit confirmation"
            )
        if not (node.get("origin") == "editor" and args.origin == "codex"):
            node["origin"] = args.origin
        node["updated_at"] = utc_now()
        bump_and_event(
            data,
            "node_updated",
            f"Updated {args.node}: {', '.join(sorted(changed))}",
            node_id=args.node,
            fields=sorted(changed),
            actor=args.origin,
        )
        save_map(map_path, data)
        render_map(map_path)
    print(json.dumps(node, ensure_ascii=False))
    return 0


def command_checkpoint(args: argparse.Namespace) -> int:
    map_path = Path(args.map).resolve()
    with file_lock(map_path):
        data = load_map(map_path)
        require_revision(data, args.expected_revision, "checkpoint")
        checkpoint = {
            "id": f"cp-{uuid.uuid4().hex[:10]}",
            "message": args.message,
            "status": args.status,
            "timestamp": utc_now(),
            "revision": data["revision"] + 1,
        }
        data["checkpoints"].append(checkpoint)
        if args.task_status:
            data["task"]["status"] = args.task_status
        bump_and_event(data, "checkpoint", args.message, status=args.status)
        save_map(map_path, data)
        render_map(map_path)
    print(json.dumps(checkpoint, ensure_ascii=False))
    return 0


def command_status(args: argparse.Namespace) -> int:
    map_path = Path(args.map).resolve()
    data = load_map(map_path)
    print(json.dumps({
        "map": str(map_path),
        "task_id": data["task_id"],
        "task": data["task"]["title"],
        "revision": data["revision"],
        "nodes": len(data["nodes"]),
        "checkpoints": len(data["checkpoints"]),
    }, ensure_ascii=False))
    return 0


def command_render(args: argparse.Namespace) -> int:
    html_path, md_path = render_map(args.map)
    print(json.dumps({"html": str(html_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    data = load_map(args.map)
    print(json.dumps({"valid": True, "nodes": len(data["nodes"]), "revision": data["revision"]}, ensure_ascii=False))
    return 0


def diff_events(old: dict[str, Any], new: dict[str, Any], revision: int) -> list[dict[str, Any]]:
    old_nodes = {node["id"]: node for node in old.get("nodes", [])}
    new_nodes = {node["id"]: node for node in new.get("nodes", [])}
    events: list[dict[str, Any]] = []
    for node_id in sorted(set(new_nodes) - set(old_nodes)):
        events.append(make_event("node_added", f"Editor added {node_id}", revision, node_id=node_id))
    for node_id in sorted(set(old_nodes) - set(new_nodes)):
        events.append(make_event("node_deleted", f"Editor deleted {node_id}", revision, node_id=node_id))
    for node_id in sorted(set(old_nodes) & set(new_nodes)):
        fields = [
            key
            for key in ("parent_id", "title", "summary", "kind", "status", "artifacts")
            if old_nodes[node_id].get(key) != new_nodes[node_id].get(key)
        ]
        if fields:
            events.append(
                make_event(
                    "node_updated",
                    f"Editor updated {node_id}: {', '.join(fields)}",
                    revision,
                    node_id=node_id,
                    fields=fields,
                )
            )
    return events


class MapServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], map_path: Path, token: str):
        super().__init__(address, MapHandler)
        self.map_path = map_path
        self.token = token
        self.lock = threading.Lock()


class MapHandler(BaseHTTPRequestHandler):
    server: MapServer

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[map] " + (format % args) + "\n")

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
        )
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-Map-Token", "") == self.server.token

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"", "/", "/index.html"}:
            with self.server.lock:
                data = load_map(self.server.map_path)
            body = render_html(data).encode("utf-8")
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if parsed.path == "/api/map":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid token"})
                return
            with self.server.lock:
                data = load_map(self.server.map_path)
            self._json(HTTPStatus.OK, data)
            return
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/map":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid token"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid body size"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc}"})
            return

        incoming = payload.get("map") if isinstance(payload, dict) else None
        expected_revision = payload.get("expected_revision") if isinstance(payload, dict) else None
        if not isinstance(incoming, dict) or not isinstance(expected_revision, int):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "map and expected_revision are required"})
            return
        errors = validate_map(incoming)
        if errors:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid map", "details": errors})
            return

        with self.server.lock, file_lock(self.server.map_path):
            current = load_map(self.server.map_path)
            if expected_revision != current["revision"]:
                self._json(
                    HTTPStatus.CONFLICT,
                    {
                        "error": "revision conflict",
                        "expected_revision": expected_revision,
                        "current_revision": current["revision"],
                        "map": current,
                    },
                )
                return
            if incoming["task_id"] != current["task_id"]:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "task_id cannot change"})
                return

            new_revision = current["revision"] + 1
            for node in incoming["nodes"]:
                old = next((item for item in current["nodes"] if item["id"] == node["id"]), None)
                if old is None or old != node:
                    node["origin"] = "editor"
                    node["updated_at"] = utc_now()
            incoming["revision"] = new_revision
            new_events = diff_events(current, incoming, new_revision)
            incoming["events"] = current["events"] + new_events
            incoming["checkpoints"] = current["checkpoints"]
            incoming["task"] = current["task"]
            incoming["task"]["updated_at"] = utc_now()
            save_map(self.server.map_path, incoming, append_event_file=False)
            append_events(self.server.map_path.parent / "events.jsonl", new_events)
            render_map(self.server.map_path)

        self._json(HTTPStatus.OK, incoming)


def command_serve(args: argparse.Namespace) -> int:
    map_path = Path(args.map).resolve()
    load_map(map_path)
    token = secrets.token_urlsafe(24)
    server = MapServer(("127.0.0.1", args.port), map_path, token)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(json.dumps({"url": url, "map": str(map_path)}, ensure_ascii=False), flush=True)
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a new branch map")
    init.add_argument("--workspace", default=".", help="Workspace that will contain .codex-mindmap")
    init.add_argument("--task", required=True, help="Task title")
    init.add_argument("--goal", help="Optional task goal")
    init.set_defaults(func=command_init)

    add = subparsers.add_parser("add", help="Add a child node")
    add.add_argument("--map", required=True)
    add.add_argument("--expected-revision", type=int, required=True)
    add.add_argument("--parent", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--summary", default="")
    add.add_argument("--kind", choices=sorted(KINDS), default="step")
    add.add_argument("--status", choices=sorted(STATUSES), default="todo")
    add.add_argument("--origin", choices=sorted(ORIGINS), default="codex")
    add.add_argument("--artifact", dest="artifacts", action="append", help="Artifact path; repeatable")
    add.set_defaults(func=command_add)

    update = subparsers.add_parser("update", help="Update a node")
    update.add_argument("--map", required=True)
    update.add_argument("--expected-revision", type=int, required=True)
    update.add_argument("--node", required=True)
    update.add_argument("--title")
    update.add_argument("--summary")
    update.add_argument("--kind", choices=sorted(KINDS))
    update.add_argument("--status", choices=sorted(STATUSES))
    update.add_argument("--origin", choices=sorted(ORIGINS), default="codex")
    update.add_argument("--artifact", dest="artifacts", action="append", help="Replace artifacts; repeatable")
    update.add_argument("--allow-editor-overwrite", action="store_true", help="Allow Codex to update a node after explicit user confirmation")
    update.set_defaults(func=command_update)

    checkpoint = subparsers.add_parser("checkpoint", help="Record a checkpoint")
    checkpoint.add_argument("--map", required=True)
    checkpoint.add_argument("--expected-revision", type=int, required=True)
    checkpoint.add_argument("--message", required=True)
    checkpoint.add_argument("--status", default="info", choices=["info", "decision", "blocked", "done"])
    checkpoint.add_argument("--task-status", choices=["active", "done", "blocked", "paused"])
    checkpoint.set_defaults(func=command_checkpoint)

    status = subparsers.add_parser("status", help="Read the current revision and summary")
    status.add_argument("--map", required=True)
    status.set_defaults(func=command_status)

    render = subparsers.add_parser("render", help="Regenerate HTML and Mermaid")
    render.add_argument("--map", required=True)
    render.set_defaults(func=command_render)

    validate = subparsers.add_parser("validate", help="Validate map JSON")
    validate.add_argument("--map", required=True)
    validate.set_defaults(func=command_validate)

    serve = subparsers.add_parser("serve", help="Serve the local editor")
    serve.add_argument("--map", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true")
    serve.set_defaults(func=command_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())