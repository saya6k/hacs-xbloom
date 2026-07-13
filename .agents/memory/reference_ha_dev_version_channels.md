---
name: ha-dev-version-channels
description: How to find/install HA dev (nightly) builds — PyPI has no .dev releases; check version.home-assistant.io/dev.json; git installs report dev0
metadata: 
  node_type: memory
  type: reference
  originSessionId: 72d7e887-0913-442e-b074-4480f7d22cfd
---

When a spec/floor needs an unreleased HA version (user prefers targeting dev
nightlies rather than waiting for beta — confirmed 2026-07-11 during the LLM
platform migration spec):

- PyPI `homeassistant` has **no `.dev` builds ever** (betas/stables only) — don't
  write a pip floor like `>=2026.8.0.devXXXX`, it can't resolve.
- The current nightly version string comes from
  `https://version.home-assistant.io/dev.json` → `.homeassistant.default`,
  format `2026.8.0.dev + YYYYMMDDHHMM` (date **and time**, not just date).
  Nightlies ship only as Docker/HAOS images.
- `pip install git+https://github.com/home-assistant/core@<sha>` self-reports
  `2026.8.0.dev0` (pyproject fixed value), which sorts *below* any date-stamped
  nightly — git installs can't match a date-stamped floor string.
- **Preferred (user-chosen 2026-07-11): use the nightly Docker image as the
  devcontainer base** — `homeassistant/home-assistant:<date-stamped tag>`
  (Docker Hub tags match the version string exactly). Then hacs.json floor,
  `requirements_test.txt` floor, and the image tag can all share one string,
  and `requirements_test.txt`'s `homeassistant>=<tag>` is satisfied by the
  preinstalled copy.
- **Container verification on this host uses Apple's `container` CLI** (no
  docker/podman installed; user correction 2026-07-11). Start services with
  `container system start` if needed; docker-like syntax:
  `container run --rm --entrypoint /bin/bash -v <repo>:/workspaces/x -w
  /workspaces/x homeassistant/home-assistant:<tag> -c "..."`. Subcommand is
  `container image list` (singular). kakao-map was tested the same way.
- **Proven reference: `~/Projects/hacs-kakao-map`** (user applied it there
  first) — copy its `.devcontainer/devcontainer.json`: `runArgs:
  ["--entrypoint", "/bin/bash", "-p", "8123:8123"]` + `overrideCommand: true`
  (kills s6 auto-start), `remoteUser: root`, interpreter
  `/usr/local/bin/python3`. Its `scripts/setup` needs no apk/apt at all — the
  image bundles ffmpeg/go2rtc/PyTurboJPEG/aioesphomeapi/bleak; only pip-install
  dev tools (ruff/pytest). Its `scripts/test-dev` phacc workaround is only
  needed for repos using pytest-homeassistant-custom-component.
- Nightly cut time matters: a PR merged after ~03:00 UTC isn't in that day's
  nightly — check mergedAt vs the version timestamp.

Applied in [[llm-platform-migration]] (tasks/2026-07-llm-platform-migration-spec.md).
