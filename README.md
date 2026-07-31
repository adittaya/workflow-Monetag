# Monetag TUI

24/7 Monetag SmartLink automation — deploy, manage, and monitor endless relay chains on GitHub Actions.

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-monetag/main/install.sh | bash
```

Installs the TUI launcher (`monetag`).

## Usage

```bash
monetag
```

Interactive terminal UI for accounts, deployment, sync, status, logs, and settings.

## How it works

Each deployed repo runs a GitHub Actions workflow (`monetag.yml`) that:
1. Gets a premium proxy from the Supabase pool
2. Drives a view to your Monetag SmartLink (`go.oclasrv.com/afu.php?zoneid=...`)
3. Follows the SmartLink redirect chain and verifies the landing view via a multi-signal scoring system
4. Writes `view_report.json` with per-view verdicts (VIEW_VERIFIED / VIEW_LIKELY / VIEW_WEAK / VIEW_BLOCKED / VIEW_INVALID)
5. On success, triggers the next run via repository_dispatch (endless relay chain)
6. On failure, invalidates the proxy and still continues the chain

Cron fallback every hour.

## Core components

- `monetag_automation.py` — SmartLink view engine + multi-signal view verification
- `proxy_rotator.py` — Supabase proxy pool rotation (dead/used tracking, blacklist)
- `profile_generator.py` — randomized browser profiles (UA, viewport, DPR)
- `config.py` — local config at `~/.config/monetag/config.json`
- `monetag.yml` — GitHub Actions relay workflow
- `tui.py` — deployment manager (repos prefixed `monetag-`)
