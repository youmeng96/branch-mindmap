# Branch Mindmap

[中文](README.md)

A cross-runtime Agent Skill and local editor that turns actionable AI work into an editable, traceable branch map.

Works with Codex, Claude Code, Cursor, OpenClaw, DeepSeek Harness, and other Agent Skills-compatible runtimes. It uses Python standard library only.

## Features

- Maps file changes, tool use, research, design, coding, tests, and multi-step decisions.
- Skips pure Q&A and casual conversation.
- Editable HTML tree with zoom, collapse, node editing, status changes, and exports.
- Revision-aware saves and `409` conflict detection.
- Cross-process locking for CLI and browser writers.
- Editor provenance protection.
- Mermaid export and append-only event history.

## Install

Auto-detect the current runtime:

```bash
npx skills add youmeng96/branch-mindmap -g
```

Or select a runtime explicitly:

```bash
npx skills add youmeng96/branch-mindmap -g -a codex
npx skills add youmeng96/branch-mindmap -g -a claude-code
npx skills add youmeng96/branch-mindmap -g -a cursor
# Install to multiple runtimes:
npx skills add youmeng96/branch-mindmap -g -a codex claude-code cursor
```

`-g` installs at user scope; omit it for a project-local install.

Typical install directories:

| Runtime | Directory |
|---|---|
| Codex | `~/.codex/skills/branch-mindmap/` |
| Claude Code | `~/.claude/skills/branch-mindmap/` |
| Cursor | `~/.cursor/skills/branch-mindmap/` |
| OpenClaw | `~/.openclaw/workspace/skills/branch-mindmap/` |
| DeepSeek Harness | `~/.dsh/skills/branch-mindmap/` |

## Use

```text
Use the branch-mindmap skill to map this task and keep branches visible at decision checkpoints.
```

For Codex, `$branch-mindmap` is also supported.

## CLI

All commands use the installed Skill root:

```bash
python <skill-root>/scripts/mapctl.py init --workspace . --task "Task" --goal "Goal"
python <skill-root>/scripts/mapctl.py status --map <map.json>
python <skill-root>/scripts/mapctl.py add --map <map.json> --expected-revision <revision> --parent n-0001 --title "Step" --kind step
python <skill-root>/scripts/mapctl.py checkpoint --map <map.json> --expected-revision <revision> --message "Checkpoint" --status info
python <skill-root>/scripts/mapctl.py render --map <map.json>
python <skill-root>/scripts/mapctl.py validate --map <map.json>
python <skill-root>/scripts/mapctl.py serve --map <map.json>
```

`agents/openai.yaml` is optional Codex UI metadata. `.codex-mindmap/` is a backward-compatible local directory name, not a runtime dependency.

## Validate

```bash
python -m unittest discover -s tests -v
python <skill-root>/scripts/mapctl.py validate --map <map.json>
```

## Compatibility notes

See [`references/runtime-compatibility.md`](references/runtime-compatibility.md).

## Limitations

- v0.1.x does not include drag sorting or multi-user collaboration.
- The Skill relies on the Agent updating checkpoints; it is not a runtime hook.
- The map is a work record, not a substitute for testing.

## License

MIT. See [`LICENSE`](LICENSE).