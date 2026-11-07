from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mapctl  # noqa: E402


class MapctlTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)

    def init_map(self) -> Path:
        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_init(
                argparse.Namespace(
                    workspace=str(self.workspace),
                    task="测试分支任务",
                    goal="验证交互式导图的核心流程",
                )
            )
        maps = list((self.workspace / ".codex-mindmap").glob("*/map.json"))
        self.assertEqual(len(maps), 1)
        return maps[0]

    def test_init_add_update_checkpoint_and_render(self) -> None:
        map_path = self.init_map()
        data = mapctl.load_map(map_path)
        self.assertEqual(data["revision"], 1)
        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(data["nodes"][0]["status"], "active")

        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_add(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=1,
                    parent="n-0001",
                    title="比较方案",
                    summary="列出两个候选实现",
                    kind="decision",
                    status="todo",
                    origin="codex",
                )
            )
        data = mapctl.load_map(map_path)
        self.assertEqual(len(data["nodes"]), 2)
        self.assertEqual(data["revision"], 2)

        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_update(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=2,
                    node="n-0002",
                    title=None,
                    summary=None,
                    kind=None,
                    status="done",
                    origin="codex",
                )
            )
        data = mapctl.load_map(map_path)
        self.assertEqual(data["nodes"][1]["status"], "done")
        self.assertEqual(data["revision"], 3)

        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_checkpoint(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=3,
                    message="方案比较完成",
                    status="info",
                    task_status="active",
                )
            )
        data = mapctl.load_map(map_path)
        self.assertEqual(len(data["checkpoints"]), 1)
        self.assertTrue((map_path.parent / "mindmap.html").exists())
        self.assertTrue((map_path.parent / "mindmap.md").exists())
        event_lines = (map_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(event_lines), 4)
        self.assertEqual(json.loads(event_lines[-1])["type"], "checkpoint")

    def test_editor_origin_requires_explicit_overwrite(self) -> None:
        map_path = self.init_map()
        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_add(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=1,
                    parent="n-0001",
                    title="用户编辑的分支",
                    summary="",
                    kind="branch",
                    status="todo",
                    origin="editor",
                )
            )
        with self.assertRaises(ValueError):
            mapctl.command_update(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=2,
                    node="n-0002",
                    title=None,
                    summary=None,
                    kind=None,
                    status="done",
                    origin="codex",
                    allow_editor_overwrite=False,
                )
            )
        with contextlib.redirect_stdout(io.StringIO()):
            mapctl.command_update(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=2,
                    node="n-0002",
                    title=None,
                    summary=None,
                    kind=None,
                    status="done",
                    origin="codex",
                    allow_editor_overwrite=True,
                )
            )
        node = next(node for node in mapctl.load_map(map_path)["nodes"] if node["id"] == "n-0002")
        self.assertEqual(node["status"], "done")
        self.assertEqual(node["origin"], "editor")

    def test_stale_cli_revision_is_rejected(self) -> None:
        map_path = self.init_map()
        with self.assertRaises(ValueError):
            mapctl.command_add(
                argparse.Namespace(
                    map=str(map_path),
                    expected_revision=99,
                    parent="n-0001",
                    title="过期写入",
                    summary="",
                    kind="step",
                    status="todo",
                    origin="codex",
                )
            )
        self.assertEqual(mapctl.load_map(map_path)["revision"], 1)

    def test_cycle_is_rejected(self) -> None:
        data = mapctl.load_map(self.init_map())
        data["nodes"].append(
            mapctl.make_node("n-0002", "B", parent_id="n-0003")
        )
        data["nodes"].append(
            mapctl.make_node("n-0003", "C", parent_id="n-0002")
        )
        errors = mapctl.validate_map(data)
        self.assertTrue(any("cycle detected" in error for error in errors))

    def test_missing_parent_is_rejected(self) -> None:
        data = mapctl.load_map(self.init_map())
        data["nodes"].append(mapctl.make_node("n-0002", "B", parent_id="n-9999"))
        errors = mapctl.validate_map(data)
        self.assertTrue(any("parent_id does not exist" in error for error in errors))

    def test_server_revision_conflict(self) -> None:
        map_path = self.init_map()
        token = "test-token"
        server = mapctl.MapServer(("127.0.0.1", 0), map_path, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        request = Request(
            base + "/api/map",
            headers={"X-Map-Token": token},
        )
        with urlopen(request, timeout=3) as response:
            current = json.loads(response.read().decode("utf-8"))

        incoming = json.loads(json.dumps(current))
        incoming["nodes"][0]["summary"] = "浏览器编辑"
        payload = json.dumps(
            {"map": incoming, "expected_revision": current["revision"]},
            ensure_ascii=False,
        ).encode("utf-8")
        save_request = Request(
            base + "/api/map",
            method="PUT",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Map-Token": token,
            },
        )
        with urlopen(save_request, timeout=3) as response:
            saved = json.loads(response.read().decode("utf-8"))
        self.assertEqual(saved["revision"], current["revision"] + 1)
        self.assertEqual(saved["nodes"][0]["origin"], "editor")

        stale_payload = json.dumps(
            {"map": incoming, "expected_revision": current["revision"]},
            ensure_ascii=False,
        ).encode("utf-8")
        stale_request = Request(
            base + "/api/map",
            method="PUT",
            data=stale_payload,
            headers={
                "Content-Type": "application/json",
                "X-Map-Token": token,
            },
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(stale_request, timeout=3)
        self.assertEqual(context.exception.code, 409)

    def test_server_rejects_missing_token(self) -> None:
        map_path = self.init_map()
        server = mapctl.MapServer(("127.0.0.1", 0), map_path, "secret")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/api/map"
        with self.assertRaises(HTTPError) as context:
            urlopen(url, timeout=3)
        self.assertEqual(context.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
