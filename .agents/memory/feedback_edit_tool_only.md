---
name: feedback-edit-tool-only
description: "Use the Edit tool for file modifications, never a Bash/Python script to rewrite file content directly, even when Edit's exact-string matching is annoying."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e1a0bef0-7dae-428e-8950-ee08cd2ab7c9
---

Never use Bash (e.g. a Python snippet doing read/splice-lines/write) to modify a tracked project file, even to work around an Edit `old_string` mismatch. Re-read the file to get the exact current text and retry Edit properly instead.

**Why:** User rejected a tool call where, after an `Edit` failed to match `old_string` (likely due to line-wrapping/whitespace differing from what I remembered), I fell back to a Python script in Bash that spliced lines 154-202 directly into `AGENTS.md`. This bypasses the harness's diff/review visibility that Edit provides and isn't how file edits should happen in this repo.

**How to apply:** If `Edit` fails to find `old_string`, use `Read` on the exact target range first to get precise current text (watch for line wrapping, curly vs straight quotes, em-dash variants), then retry `Edit` with the corrected string. Don't reach for Bash/Python file rewriting as a shortcut, even for large block replacements — split into smaller sequential `Edit` calls if needed.
