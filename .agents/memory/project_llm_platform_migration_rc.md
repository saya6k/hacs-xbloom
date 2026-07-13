---
name: llm-platform-migration
description: LLM tools migrated to HA 2026.8 llm platform — v1.5.0-rc.0 published on the dev-nightly floor; stable promotion gated on HA 2026.8.0b0
metadata: 
  node_type: memory
  type: project
  originSessionId: 72d7e887-0913-442e-b074-4480f7d22cfd
---

PR #50 (merged 2026-07-12) moved the 13 LLM tools to HA 2026.8's new `llm`
platform (`custom_components/xbloom/llm/`), kept the opt-in custom API
(`xbloom_coffee_<entry_id>`, name with MAC — both test-pinned), and raised
the floor to `2026.8.0.dev202607110310` (one string across hacs.json /
requirements_test.txt / devcontainer image tag). Prerelease
**v1.5.0-rc.0** published 2026-07-12 with the hand-written notes on top.

**Open gate (T5):** when HA `2026.8.0b0` ships — move the three version pins
to `2026.8.0b0`, re-run the CP-B checks (platform hook / `LLMTools` contract
may still drift before beta), publish a fresh rc, then promote the stable
v1.5.0 draft. Full plan/spec/todo in `tasks/2026-07-llm-platform-migration-*.md`
(gitignored, local only). AGENTS.md's "LLM tools platform" section documents
the AST-pinned lazy-loading invariants — don't break them when refactoring.

CI facts confirmed on PR #50: hacs/action accepts a dev-nightly floor
string; hassfest accepts a package-style `llm/` platform. See
[[ha-dev-version-channels]] for the version/devcontainer mechanics.
