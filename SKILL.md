---
name: branch-mindmap
description: |
  为每一个可执行的 Codex 任务维护一张可编辑、可追溯的分支思维导图：当任务会修改文件、运行工具、调查资料、设计方案、编写代码、执行测试或包含多步决策时自动使用。
  在关键检查点更新导图，让用户看清当前分支、证据、产物和待决策项；纯知识问答不建图。Use for actionable tasks that change files, run tools, investigate, design, code, test, or involve multi-step decisions. Do not use for pure Q&A.
metadata:
  author: "Branch Mindmap Contributors"
  version: "0.1.0"
  repository: "https://github.com/youmeng96/"
---

# Branch Mindmap

让 Codex 的工作过程变成一张用户能看懂、能修改、能追溯的分支树，而不是只留在聊天记录里的连续文本。

## 何时启用

启用条件：任务至少包含一个可执行动作，例如读取或修改文件、运行命令、调查资料、设计方案、编码、测试、部署或需要用户在多个分支间选择。

不要启用：纯知识问答、单句解释、无需工具且没有分支的闲聊。此时直接用文字回答，不创建 `.codex-mindmap` 文件。

## 核心规则

1. **每任务一张图**：同一任务复用同一个 `map.json`，不要重复初始化。
2. **关键检查点更新**：开始、计划成形、出现分支、重大修改前、验证后、用户编辑后、完成时更新。
3. **不记录每次工具调用**：导图记录决策和结果，不把每个 shell 命令都变成节点。
4. **分支必须可判断**：需要用户偏好时，使用 `decision` 节点列出选项、影响和建议，并标记 `🔴 CHECKPOINT · 🛑 STOP`，等待确认。
5. **用户编辑优先**：浏览器保存的节点是用户意图。Codex 写图前必须重新读取最新 `revision`，不得覆盖用户修改；更新 `origin: "editor"` 的节点必须显式使用 `--allow-editor-overwrite`，且仅在用户确认后使用。
6. **证据可追溯**：节点摘要写明判断依据；产物路径写入 `artifacts`；关键变化写入 `events.jsonl`。

## 路径约定

下列命令中的 `<skill-root>` 是 `branch-mindmap` 的安装目录。不要假设 Codex 的工作目录等于 Skill 目录。

- Windows: `$HOME\.codex\skills\branch-mindmap`
- macOS / Linux: `$HOME/.codex/skills/branch-mindmap`

## 初始化

任务开始时，从工作区根目录运行：

```bash
python <skill-root>/scripts/mapctl.py init --workspace . --task "<任务标题>" --goal "<一句话目标>"
```

记录命令返回的 `map.json` 路径，再读取当前 revision：

```bash
python <skill-root>/scripts/mapctl.py status --map <map.json>
```

随后为已知的主要步骤、决策、风险和预期产物添加节点。所有 CLI 写入都必须带 `--expected-revision`：

```bash
python <skill-root>/scripts/mapctl.py add --map <map.json> --expected-revision <revision> --parent n-0001 --title "<步骤>" --kind step
```

命令返回 revision 冲突时，停止写入，重新运行 `status`，读取最新图后合并再重试。CLI 与本地服务共享跨进程锁，读取—校验—写入不会被并发写入穿透。

节点类型：

- `goal`：任务目标。
- `step`：可执行步骤。
- `decision`：需要用户选择的决策点。
- `branch`：已经分叉出的方案。
- `artifact`：文件、代码、文档或发布产物。
- `risk`：风险、阻塞和待验证假设。

节点状态：`todo`、`active`、`done`、`blocked`、`rejected`。

## 检查点协议

在以下时机执行 `checkpoint`，然后重新读取 `map.json`：

- 形成初始计划后。
- 发现新的方案分支或推翻旧方案时。
- 修改多个文件、执行迁移、删除数据或其他重大操作前。
- 测试、构建、调研或验证返回新证据后。
- 用户手动编辑导图后。
- 任务完成或停止时。

```bash
python <skill-root>/scripts/mapctl.py checkpoint --map <map.json> --expected-revision <revision> --message "<发生了什么>" --status info
```

如果某个分支必须由用户决定，标记：

**🔴 CHECKPOINT · 🛑 STOP：用户确认前不要继续依赖该决策的动作。**


```bash
python <skill-root>/scripts/mapctl.py checkpoint --map <map.json> --expected-revision <revision> --message "<需要选择的原因>" --status decision
```

然后向用户展示：

- 每个选项。
- 每个选项的代价和风险。
- 推荐选项及理由。
- 用户确认前不要继续依赖该决策的动作。

## 用户编辑流程

需要可编辑界面时启动本地服务：

```bash
python <skill-root>/scripts/mapctl.py serve --map <map.json>
```

服务只绑定 `127.0.0.1`，使用临时令牌，并把浏览器的修改原子写回 `map.json`。如果无法打开浏览器，继续使用 `map.json`、`mindmap.md` 和 CLI。

用户说“我改过了”“刷新导图”或出现新的 `revision` 时：

1. 重新读取 `map.json`，不要使用对话中的旧副本。
2. 把浏览器修改视为约束。
3. 如果同一节点同一字段与 Codex 计划冲突，创建 `risk` 或 `decision` 节点并请求用户决定。
4. 不得静默覆盖 `origin: "editor"` 的修改。
5. Codex 若必须更新用户编辑过的节点，先得到明确确认，再使用 `--allow-editor-overwrite`；节点仍保留 `origin: "editor"`，事件记录实际执行者。

## 失败处理矩阵

| 失败 | 必须做什么 | 不要做什么 |
|---|---|---|
| 找不到 `map.json` | 先搜索当前任务的 `.codex-mindmap`；仍然不存在时再询问是否初始化 | 自动新建第二张图掩盖丢失 |
| 存在多张候选导图 | 按任务标题、时间和 `task_id` 展示候选，让用户选择 | 猜测并覆盖任意一张 |
| JSON 损坏或校验失败 | 保留原文件，报告错误位置，修复后用 `validate` 复核 | 用空图覆盖损坏文件 |
| `parent_id` 不存在或出现环 | 拒绝保存，修正节点关系后重新验证 | 静默断开或重建整棵树 |
| 工作区不可写 | 输出可复制的 `map.json`/`mindmap.md` 内容并报告权限问题 | 声称已经保存 |
| 脚本不可用或 Python 缺失 | 停止写图，报告缺失依赖；保留文本版导图 | 伪造 CLI 成功结果 |
| 默认端口被占用 | 使用 `--port 0` 让系统分配端口 | 改用 `0.0.0.0` 或外部端口 |
| 浏览器无法打开 | 继续使用 `mindmap.html`、`mindmap.md` 和 CLI | 声称用户已经看到页面 |
| 静态 HTML 编辑未落盘 | 要求导出 JSON 或改用本地服务保存；检查 revision 是否真的变化 | 把内存中的修改当成已保存 |
| CLI 或浏览器保存冲突 | 读取最新 revision，合并后重试；无法合并时创建 `decision` 节点 | 无 revision 直接写文件 |
| 用户删除或被否决分支 | 读取最新图并遵守删除/否决决定 | 擅自恢复或继续执行该分支 |

## 渲染与验证

每次结构变化后重新渲染：

```bash
python <skill-root>/scripts/mapctl.py render --map <map.json>
python <skill-root>/scripts/mapctl.py validate --map <map.json>
```

- `mindmap.html`：离线可看的可编辑界面；通过本地服务打开时可写回。
- `mindmap.md`：Mermaid 版本，适合 GitHub 和文档。
- `events.jsonl`：追加式变更历史。
- `map.json`：唯一事实源。

## 高风险任务与回滚条件

用户说“保证可以回滚”时，把承诺改成可验证条件，不直接保证结果：

1. 检查版本控制状态、当前分支、基线提交和未提交修改。
2. 没有 Git 或工作区不干净时，建立备份或 `decision` 节点，说明风险。
3. 在重大修改前写入基线提交、备份路径、影响范围和回滚命令。
4. 回滚方案必须实际可执行；迁移任务还要验证回退脚本。
5. 完成前执行一次回滚验证或可逆性检查，把结果写入导图和 `artifacts`。
6. 回滚条件未建立时，标记 `🔴 CHECKPOINT · 🛑 STOP`，不要开始不可逆修改。

## 完成条件

任务结束时：

1. 把已完成节点标记为 `done`，被放弃的方案标记为 `rejected`。
2. 记录最终产物路径。
3. 写入 `done` 检查点并更新任务状态。
4. 验证 `map.json` 和 `mindmap.md`。
5. 向用户报告导图路径和仍未解决的风险。

## 详细规范

- `references/map-schema.md`：JSON 字段、状态约束和冲突规则。
- `references/workflow.md`：自动启用、检查点、分支等待和用户编辑流程。
- `assets/map_editor.html`：离线编辑器模板。
- `scripts/mapctl.py`：CLI、渲染器和本地服务。

## 不要做

- 不为纯知识问答创建 `.codex-mindmap`。
- 不把每次 shell 命令都变成节点。
- 不静默覆盖用户编辑或 `origin: "editor"` 的字段。
- 不在 revision 冲突后直接写文件。
- 不在同一任务重复初始化导图。
- 不重建用户已删除或标记为 rejected 的分支。
- 不在回滚条件未建立时执行不可逆修改。
- 不把静态 HTML 中未落盘的编辑当作已保存。
- 不自动提交 `.codex-mindmap` 到 Git。
- 不把本地编辑器暴露到 `0.0.0.0` 或外部网络。
- 不声称这是运行时 hook；它依靠 Codex 在检查点主动执行。
- 不在未验证 `map.json` 的情况下宣称任务完成。

## 诚实边界

- Skill 依靠 Codex 在检查点主动写图，不能替代运行时级 hook。
- 不在每次工具调用后刷新，避免噪音、延迟和成本。
- 导图是工作记忆，不是完成任务的证明；最终结果仍需真实测试。