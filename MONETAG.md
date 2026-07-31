# Monetag SmartLink Automation — System Analysis

Deep dive into the Monetag SmartLink automation system: how the SmartLink works, how the engine drives and verifies views, how the proxy pool integrates, and how the CI relay chain keeps it running 24/7.

---

## 1. Monetag SmartLink mechanics

Monetag's **SmartLink** is a single URL that the network repurposes into the "best converting" offer for each visitor. It is not a fixed landing page.

- **Direct Link format:** `https://go.oclasrv.com/afu.php?zoneid=XXXXX`
  - `go.oclasrv.com` is the click-gateway domain
  - `afu.php` is the click handler
  - `zoneid` is your placement/zone identifier
- **Redirect flow (per Monetag docs):**
  1. Visitor opens the SmartLink
  2. Monetag captures the click and transfers user data (geo, device, browser, referrer, OS)
  3. The AI optimizer picks the highest-paying offer matching that profile
  4. The browser is redirected through a chain (HTTP 30x → meta-refresh → JS `location`) to the rotating offer page
- **Why this matters for automation:** the actual offer domain is never predictable ahead of time. A "view" is only genuine if the browser demonstrably **left the Monetag network** and rendered a real third-party offer page. That fact drives the entire verification design below.

### Domains involved

| Role | Domains |
|------|---------|
| SmartLink gateway | `go.oclasrv.com`, `oclasrv.com` |
| Network surface | `monetag.com`, `smart.monetag.com` |
| Ad networks (still not "a view") | propellerads, adskeeper, adsterra, googleadservices, doubleclick, taboola, outbrain, mgid, popads, … |

The engine treats any final URL on the `AD_NETWORK_DOMAINS` list as **not a genuine view** — the chain has to land on something outside the ad ecosystem.

---

## 2. View lifecycle (`run_view_cycle`)

One view cycle = one visit from a fresh browser session:

1. `_create_driver()` — new headless/headed Chrome, unique profile (UA, viewport, DPR), stealth JS injected, optional `MONETAG_PROXY`.
2. `PageMonitor` installs a MutationObserver + fetch/XHR interceptor to record page growth and network evidence.
3. SmartLink URL (with UTM/traffic-source params) is opened.
4. `follow_redirect_chain()` polls until the URL+content stabilizes, handling:
   - HTTP 30x redirects
   - meta-refresh and JS `location` redirects
   - **JS-only redirects recovered from raw HTML** when the page never leaves the smartlink domain
   - **Cloudflare challenge** (detected via `cf-browser-verification`/`challenge-form`/`_cf_chl_opt` signatures) → refresh once and re-poll
5. `scan_tabs_for_view()` — SmartLinks frequently open a **popunder/popup**; the engine scans all tabs and selects the most content-rich non-ad tab as the genuine view.
6. Human dwell (`human_read`, `human_scroll`, `bezier_move`) — gives the offer page time to load trackers and keeps the session human-like.
7. `verify_view()` scores the view across 7 signals.

### Adaptive timeouts

`AdaptiveTimeout` tracks historical page-load and nav latencies and dynamically sets page-load / script timeouts so slow offers don't get killed early and fast ones aren't wasted waiting.

---

## 3. View verification — the 7-signal scoring system

Total = 100 points. Higher score = more evidence a real human-rendered offer page loaded.

| Signal | Weight | How it's scored |
|--------|-------:|-----------------|
| `left_network` | 20 | 20 = ≥1 chain hop and final URL off the ad network; 10 = no hops; 5 = still on smartlink domain; 0 = on an ad network |
| `page_rendered` | 20 | readyState=complete + body ≥300 chars + ≥50 elements = 20; graded down to 4 for thin pages |
| `js_healthy` | 10 | `navigator.webdriver=false`, window loaded, no console crash (`verify_js_working`) |
| `not_blocked` | 15 | 15 = clean; 8 = Cloudflare seen but survived; 5 = very short body; 0 = block signature matched |
| `offer_signals` | 15 | app_store/telegram/whatsapp/offer_landing = 15; affiliate_tracker = 11; content_page = 9; buttons add bonus |
| `network_evidence` | 10 | ≥15 tracked resources = 10; graded down; recent fetch/XHR activity counts |
| `dwell_time` | 10 | min(10, human dwell seconds) — rewards pages that stayed open |

**Block signatures** (`detect_block_signature`): captcha, "verify you are human", "access denied", "forbidden", "404", "sorry, you have been blocked", CF challenge markers, empty body shells.

### Verdict thresholds

| Verdict | strict | lenient |
|---------|-------:|--------:|
| VIEW_VERIFIED | ≥ 85 | ≥ 80 |
| VIEW_LIKELY | ≥ 65 | ≥ 55 |
| VIEW_WEAK | ≥ 45 | ≥ 30 |
| VIEW_BLOCKED | ≥ 20 | ≥ 10 |
| VIEW_INVALID | < 20 | < 10 |

### Exit codes (worst across all views)

- `0` — all views VERIFIED/LIKELY
- `2` — any BLOCKED or INVALID (also: cycle crashed, proxy navigation failure)
- `3` — any WEAK

---

## 4. Traffic source simulation

`MONETAG_TRAFFIC_SOURCE` picks a referrer + UTM fingerprint:

| Source | Referrer | UTM |
|--------|----------|-----|
| youtube | `https://www.youtube.com/` | utm_source=youtube, utm_medium=referral, utm_campaign=smartlink |
| google | `https://www.google.com/` | utm_source=google, utm_medium=organic |
| facebook | `https://www.facebook.com/` | utm_source=facebook, utm_medium=social |
| twitter | `https://x.com/` | utm_source=twitter, utm_medium=social |
| direct | *(none)* | none |

`MONETAG_REFERER` overrides the source entirely with an exact referrer URL. UTM params are appended to the SmartLink via `_add_utm_to_url` before navigation, so Monetag's AI sees consistent, realistic traffic provenance.

---

## 5. Proxy integration

- `proxy_rotator.py` pulls proxies from Supabase `proxy_results` (`monetag_ok=true` for premium tier), ordered by latency.
- **Used tracking:** after a view, the proxy IP is written to `monetag_proxy_state` (state=`used`, TTL 24h) so the same IP isn't reused within a day.
- **Dead tracking:** blocked/invalid views delete the proxy from `proxy_results` (`mark_dead`) and flag `report_proxy_failure`.
- **Per-view rotation:** with `MONETAG_VIEWS > 1`, the engine re-fetches a fresh proxy for each cycle.
- **Selenium validation** (`test_proxy_selenium`): when `MONETAG_SMARTLINK_URL` is configured, a proxy is validated by loading the SmartLink and confirming the browser actually leaves `oclasrv.com`/`monetag.com` to an offer; otherwise it falls back to plain `monetag.com` reachability.
- Local blacklist (`proxy_blacklist.json`) keeps known-dead IPs out for 24h between runs.

---

## 6. Reporting (`view_report.json`)

Written after every run (or best-effort on failure):

```json
{
  "platform": "Monetag",
  "smartlink_url": "...",
  "views_requested": 1,
  "views_completed": 1,
  "verify_mode": "strict",
  "traffic_source": "youtube",
  "summary": {
    "VIEW_VERIFIED": 1,
    "total": 1,
    "verified_or_likely": 1,
    "landing_types": {"offer_landing": 1},
    "unique_final_domains": ["example-offer.com"]
  },
  "views": [
    {
      "final_url": "...", "landing_type": "offer_landing",
      "chain_hops": ["go.oclasrv.com/afu.php?zoneid=...", "...", "..."],
      "signals": {"left_network": 20, "...": "..."},
      "score": 92, "verdict": "VIEW_VERIFIED",
      "proxy_ip": "...", "traffic_source": "youtube", ...
    }
  ]
}
```

The CI workflow parses this summary into the step summary and decides the run status.

---

## 7. CI relay loop (`.github/workflows/monetag.yml`)

`Monetag SmartLink Loop` runs on `workflow_dispatch` (manual), `schedule` (hourly fallback), and `repository_dispatch` (relay).

1. **Validate** — SmartLink URL must be present.
2. **Setup** — Python 3.11, Google Chrome (deb, no snap), chromedriver via webdriver-manager, pip deps.
3. **Configure Supabase** — write creds via `config.py --set`.
4. **Get proxy** — `proxy_rotator.py premium`.
5. **Run engine** — up to 3 attempts; if a run finishes in <120s the proxy is assumed blocked → rotate and retry; a final direct (no-proxy) attempt is made if no views verified.
6. **Relay** — always fires (unless `no_relay=1`): dispatches `repository_dispatch` `relay` to `RELAY_TARGET_REPO` with `smartlink_url`, `traffic_source`, `verify_mode`, `views` in `client_payload`, preserving the loop config through the chain. Tries `LOOP_TRIGGER_TOKEN` then `GITHUB_TOKEN`.
7. **Summary** — writes the verdict summary to `GITHUB_STEP_SUMMARY`.

---

## 8. Local TUI (`tui.py`)

- Banner **MONETAG CONTROL**; data at `~/.monetag247` (`MONETAG_HOME`).
- Deploys instances as repos prefixed **`monetag-`** from template `adittaya/workflow-monetag`.
- Deploy flow: create repo → push template → set encrypted secrets (`SUPABASE_*`, `RELAY_TARGET_REPO`, `LOOP_TRIGGER_TOKEN`, `MONETAG_SMARTLINK_URL`) → enable + dispatch workflow.
- Status/logs screens parse the run logs for the report; Sync imports existing `monetag-*` repos; Dispatch lets you re-trigger with a SmartLink URL.

---

## 9. Environment contract

| Var | Default | Purpose |
|-----|---------|---------|
| `MONETAG_SMARTLINK_URL` | — | SmartLink to visit (required if not given as argv) |
| `MONETAG_PROXY` | — | `http://ip:port` for the session |
| `MONETAG_TRAFFIC_SOURCE` | `youtube` | youtube\|google\|facebook\|twitter\|direct |
| `MONETAG_VERIFY_MODE` | `strict` | strict\|lenient |
| `MONETAG_VIEWS` | `1` | view cycles per run |
| `MONETAG_REFERER` | — | exact referrer, overrides traffic source |
| `MONETAG_HEADLESS` | — | `"1"` forces headless |
| `MONETAG_DEBUG` | — | `"1"` saves debug screenshots |
| `MONETAG_MOBILE` | `1` | mobile profile unless `0` |
| `MONETAG_HARD_TIMEOUT` | `300` | per-cycle cap in seconds |
| `MONETAG_NONINTERACTIVE` | — | headless CI mode |

### CLI

```
python3 monetag_automation.py <smartlink_url> [--views N] [--verify-mode strict|lenient]
                                  [--traffic-source youtube|google|facebook|twitter|direct] [--debug]
```

---

## 10. Deployment checklist

1. **Supabase SQL** (`schema.sql`): create `monetag_proxy_state`, add `monetag_ok` column to `proxy_results`, RLS policies.
2. **GitHub repo** `adittaya/workflow-monetag`: push code (template for TUI deployments).
3. **Secrets on each deployed instance repo:** `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SECRET`, `RELAY_TARGET_REPO`, `LOOP_TRIGGER_TOKEN`, `MONETAG_SMARTLINK_URL`.
4. **First run:** `monetag` TUI → Accounts → Settings (Supabase + SmartLink) → Deploy.
5. Proxy pool health: `python3 proxy_rotator.py --status` / `--test ip:port`.
