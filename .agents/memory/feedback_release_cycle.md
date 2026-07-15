---
name: feedback-release-cycle
description: "For ha-xbloom BLE bug fixes, skip the devcontainer and iterate via branch -> PR -> merge -> rc prerelease, tested on the user's real HA + hardware."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a3ebf6da-07d3-47a6-8749-c89384cf7ac6
---

When fixing bugs that need real BLE hardware to verify (this project has no BLE in CI), the user tests on their own running Home Assistant instance rather than the devcontainer.

**Why:** the devcontainer's `scripts/setup` pip-installs `habluetooth`, which has no prebuilt wheel for this machine's Python/arch combo and compiles its Cython-generated C extensions from source — observed taking 30+ minutes without finishing. The user explicitly said "너무 느리다, 그냥 프리 릴리즈 해서 HA에서 테스트할게" (too slow, I'll just prerelease and test on real HA) and had me stop the devcontainer setup.

**How to apply:** for BLE/hardware-dependent fixes in this repo, don't default to booting the devcontainer for verification — go straight to: commit on a `fix/*` branch, open a PR, wait for CI (HACS validate + hassfest) to go green, merge, then find the new draft via `gh release list` (release-drafter auto-creates/updates a `v*-rc.N` draft on every merge to main) and publish it with `gh release edit <tag> --draft=false --prerelease`. The user then updates via HACS and reports back logs/behavior from their real machine. Repeat quickly — the user wants each iteration merged and released promptly rather than batched, since real-hardware testing is the actual bottleneck and each round-trip is precious. See [[ha-xbloom-release-workflow]].

Related: the release workflow itself is documented in this repo's `AGENTS.md` ("Release workflow" section) — rc/stable rolling drafts via release-drafter, publish the rc draft as prerelease once CI is green.
