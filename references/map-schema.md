# Branch Map Schema v1

`map.json` 是任务分支的唯一事实源。所有写入必须通过 `scripts/mapctl.py`，以保留校验、原子写入和事件历史。

## 顶层结构

```json
{
  "schema_version": 1,
  "task_id": "task-20261107-120000-abcd",
  "revision": 3,
  "task": {
    "id": "task-20261107-120000-abcd",
    "title": "实现登录页",
    "goal": "完成可测试的登录流程",
    "status": "active",
    "created_at": "2026-11-07T04:00:00Z",
    "updated_at": "2026-11-07T04:20:00Z"
  },
  "nodes": [],
  "checkpoints": [],
  "events": []
}
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `schema_version` | integer | 当前固定为 `1` |
| `task_id` | string | 创建后不可改变 |
| `revision` | integer | 从 `1` 开始，每次写入递增 |
| `task.status` | string | `active`、`done`、`blocked` 或 `paused` |
| `nodes` | array | 至少一个节点 |
| `checkpoints` | array | 按时间追加 |
| `events` | array | 按时间追加，浏览器写入也会生成 |

## 节点

```json
{
  "id": "n-0002",
  "parent_id": "n-0001",
  "title": "选择认证方案",
  "summary": "比较会话 Cookie 与 JWT 的安全性和实现成本",
  "kind": "decision",
  "status": "active",
  "origin": "codex",
  "artifacts": [],
  "created_at": "2026-11-07T04:05:00Z",
  "updated_at": "2026-11-07T04:10:00Z"
}
```

- `id`：唯一、稳定，格式建议 `n-0001`。
- `parent_id`：父节点 ID；根节点为 `null`。
- `kind`：`goal | step | decision | branch | artifact | risk`。
- `status`：`todo | active | done | blocked | rejected`。
- `origin`：`codex | editor`。
- `artifacts`：字符串数组，保存相对路径或 URL。
- `created_at` / `updated_at`：UTC ISO 8601 字符串。

## 检查点

```json
{
  "id": "cp-a1b2c3d4",
  "message": "完成方案比较，等待用户选择",
  "status": "decision",
  "timestamp": "2026-11-07T04:15:00Z",
  "revision": 4
}
```

检查点状态：`info | decision | blocked | done`。

## 事件

```json
{
  "id": "evt-a1b2c3d4e5f6",
  "type": "node_updated",
  "message": "Editor updated n-0002: status",
  "timestamp": "2026-11-07T04:18:00Z",
  "revision": 5,
  "node_id": "n-0002",
  "fields": ["status"]
}
```

## 校验规则

- 顶层 ID 和节点 ID 必须唯一。
- 每个非空 `parent_id` 必须指向存在的节点。
- 节点不能形成环。
- `kind`、`status` 和 `origin` 必须在允许集合内。
- `revision` 必须为正整数。
- `task_id` 创建后不可改变。
- 浏览器写入必须携带 `expected_revision`，不匹配返回 `409 Conflict`。
- CLI 的 `add`、`update`、`checkpoint` 必须携带 `--expected-revision`，不一致时拒绝写入。

## 冲突规则

1. 浏览器保存时递增 `revision`。
2. Codex 写入前重新读取最新文件。
3. 用户修改的节点标记为 `origin: "editor"`。
4. Codex 不得静默覆盖用户修改的字段。
5. 冲突无法自动合并时，建立 `risk` 或 `decision` 节点并请用户决定。