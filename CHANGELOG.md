# Changelog

All notable changes to this project are documented here.

## [0.1.1] - 2026-11-08

### Added

- Cross-runtime installation guidance for Codex, Claude Code, Cursor, OpenClaw, and DeepSeek Harness.
- `references/runtime-compatibility.md` with portable script paths and verification steps.
- Cross-runtime forward-test prompt.
- Agent Skills compatibility badge and global auto-detection install command.
- Multi-runtime install example and English quick-start README.

### Changed

- Generalized workflow instructions from Codex-only wording to AI Agent wording.
- Documented that `agents/openai.yaml` is optional Codex UI metadata.
- Documented that `.codex-mindmap/` is a backward-compatible local directory name, not a runtime dependency.
- Updated metadata version and runtime coverage.

## [0.1.0] - 2026-11-07

### Added

- Codex Skill for automatic branch maps on actionable tasks.
- Python CLI for init, add, update, checkpoint, render, validate, and serve.
- Self-contained editable HTML tree with pan, zoom, collapse, node editing, and export.
- Revision-aware local save API with token protection and conflict detection.
- Mermaid export and append-only event history.
- Unit tests for schema, CLI, rendering, auth, and conflict handling.
- Required expected-revision checks for every CLI writer.
- Failure-recovery matrix, rollback conditions, and explicit anti-pattern blacklist.
- Darwin 9-dimension quality audit and forward-test prompt set.