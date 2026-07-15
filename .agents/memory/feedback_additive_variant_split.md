---
name: feedback-additive-variant-split
description: "When splitting one entry point into per-variant versions (e.g. coffee vs tea), add a leaner sibling rather than restructuring the original — confirmed preference"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: aac0a1e2-1283-41d2-a622-2cf11d40dc2d
---

When a service/entity handles two meaningfully-different variants of a thing (e.g.
`execute_recipe` covering both coffee and tea recipes, where tea takes a completely
different BLE sequence and none of the coffee-only fields apply), the user's
preferred fix is:

- **Add** a new, narrower sibling for the variant that needs different handling
  (`execute_tea_recipe`, fields trimmed to only what applies), rather than
  splitting/renaming/removing the original.
- **Keep the original untouched** and treat it as the default/majority-case
  endpoint — don't deprecate it or restrict what it accepts, even though the new
  sibling exists.
- **Reuse the same field/key names** across the original and the new sibling
  (e.g. both use `recipe` to target a recipe) so callers/automations can move
  between them without relearning vocabulary.

**Why:** explicit instruction during the xbloom-studio-review-adoptions work
(2026-07-15) — asked to split `execute_recipe` into a tea-specific service, then
clarified: "기본을 커피로 간주, execute_tea_recipe를 추가. 대신 create나 edit
recipe에 호환이 가능하게끔 key는 동일하게 맞출 것" (treat the existing one as the
coffee default, only add the tea one, keep field names compatible with
create/edit). This is a smaller, purely-additive, zero-breakage change compared to
the alternative (splitting into `execute_coffee_recipe` + `execute_tea_recipe` and
retiring the original), which was explicitly not chosen.

**How to apply:** when a future request looks like "these two cases are different,
maybe split X" — default to proposing an additive narrower sibling first, not a
restructure, and ask before doing anything that would rename/remove an existing
service, entity, or field a user's automation might already reference. See
[[project_xbloom_studio_review_adoptions]] for the concrete instance.
