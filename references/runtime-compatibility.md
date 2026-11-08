# Runtime Compatibility

`branch-mindmap` uses the open Agent Skills structure and Python standard library. It does not call a Codex-only API.

## Recommended install

Auto-detect the current runtime:

```bash
npx skills add youmeng96/branch-mindmap -g
```

Or target a supported runtime explicitly:

```bash
npx skills add youmeng96/branch-mindmap -g -a codex
npx skills add youmeng96/branch-mindmap -g -a claude-code
npx skills add youmeng96/branch-mindmap -g -a cursor
```

The exact `-a` names available depend on the installed `skills` CLI version. If a name is rejected, run `npx skills --help` or use auto-detect.

## Manual install locations

| Runtime | Typical skill directory |
|---|---|
| Codex | `~/.codex/skills/branch-mindmap/` |
| Claude Code | `~/.claude/skills/branch-mindmap/` |
| Cursor | `~/.cursor/skills/branch-mindmap/` |
| OpenClaw | `~/.openclaw/workspace/skills/branch-mindmap/` |
| DeepSeek Harness | `~/.dsh/skills/branch-mindmap/` |
| Other runtimes | Use the runtime's documented skills directory |

Windows uses the same structure under `%USERPROFILE%`.

## Script path

Commands must point to the installed Skill root, not the user's project root:

```bash
python <skill-root>/scripts/mapctl.py init --workspace . --task "<task title>"
```

Examples:

- Codex: `python ~/.codex/skills/branch-mindmap/scripts/mapctl.py ...`
- Claude Code: `python ~/.claude/skills/branch-mindmap/scripts/mapctl.py ...`
- Cursor: `python ~/.cursor/skills/branch-mindmap/scripts/mapctl.py ...`

## What is runtime-specific

- Skill installation directory.
- Explicit invocation syntax.
- Whether `agents/openai.yaml` is read.

## What is portable

- `SKILL.md` frontmatter and Markdown instructions.
- `scripts/mapctl.py`.
- `references/map-schema.md`.
- `assets/map_editor.html`.
- The `map.json`, `events.jsonl`, `mindmap.html`, and `mindmap.md` outputs.

`.codex-mindmap/` is retained as a stable local directory name for backward compatibility. It is not a runtime dependency; other runtimes can use the same commands and may add the directory to `.gitignore`.

## Verification

From the installed Skill root:

```bash
python -m unittest discover -s tests -v
python scripts/mapctl.py init --workspace <temporary-directory> --task "runtime smoke test"
python scripts/mapctl.py validate --map <returned-map-json>
```

A runtime is portable when the same Skill folder can run this sequence from a non-Codex directory.