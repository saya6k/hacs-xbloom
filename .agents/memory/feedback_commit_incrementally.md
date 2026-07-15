---
name: feedback-commit-incrementally
description: "User wants commits made as each discrete change lands, not batched into one big end-of-session commit"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: aac0a1e2-1283-41d2-a622-2cf11d40dc2d
---

Commit each discrete change as it's finished, rather than accumulating a large
uncommitted diff across a long session and committing everything at the end.

**Why:** explicit instruction (2026-07-15) after a long session had piled up 5
unrelated features as one uncommitted diff (Bluetooth discovery, MachineInfo
telemetry, device-registry reorg, flow-rate sensor, a new service, and a
hardware-verified bugfix). Retroactively splitting that into clean commits
required manually extracting diff hunks per file (`git diff` → identify hunk
boundaries → build minimal patches → `git apply --cached`) since the changes were
too interleaved for simple whole-file `git add`. That's avoidable by committing
sooner.

**How to apply:** in this repo, after finishing a self-contained change (one
feature, one bugfix, one refactor — matching the granularity of the existing
`git log` style: `feat(scope): ...`, `fix(scope): ...`, `chore(agents): ...`),
commit it before starting the next unrelated one, rather than waiting for an
explicit "commit this" request or batching multiple features together. Still
follow the existing git-safety rules (only commit when doing agentic work in this
repo, never force-push, never amend published commits) — this is about
*frequency*, not about skipping confirmation for the destructive operations
those rules already cover. If a later request in the same turn depends on the
first change already being committed (e.g. a bugfix the user wants preserved
before a riskier follow-up), commit proactively without waiting to be asked.
