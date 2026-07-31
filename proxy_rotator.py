import os
import socket
import sys
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as req_lib

import datetime

import config


def _check_native_binary(path: str) -> bool:
    """Check if path is a real ELF binary (not a snap wrapper shell script)."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def _detect_chrome_binary() -> str:
    """Find a working Chrome/Chromium binary. Always returns a string."""
    import shutil

    candidates = [
        "/opt/google/chrome/chrome",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]

    # 1. Prefer env var
    env_path = os.environ.get("CHROMIUM_PATH", "")
    if env_path:
        candidates.insert(0, env_path)

    # 2. Search PATH via shutil (same as verifier)
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium", "google-chrome-beta"):
        which = shutil.which(name)
        if which:
            candidates.insert(0, which)

    # 3. Native ELF binary first
    for p in candidates:
        if _check_native_binary(p):
            return p

    # 4. Fallback: any existing file
    for p in candidates:
        if os.path.exists(p):
            return p

    # 5. Last resort
    return "/usr/bin/chromium-browser"

SUPABASE_REST = "/rest/v1"
TEST_URL = "https://monetag.com/"
STATE_TABLE = "/monetag_proxy_state"
STATE_TTL_HOURS = 24


def supabase_fetch(endpoint, method="GET", timeout=25, data=None):
    cfg = config.load()
    url = f"{cfg['supabase_url']}{SUPABASE_REST}{endpoint}"
    headers = {
        "apikey": cfg.get("supabase_secret") or cfg.get("supabase_key", ""),
        "Authorization": f"Bearer {cfg.get('supabase_secret') or cfg.get('supabase_key', '')}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    try:
        resp = req_lib.request(method, url, headers=headers, data=body, timeout=timeout)
        return resp
    except Exception as e:
        raise RuntimeError(f"Supabase request failed: {e}")


def fetch_proxies(tier="premium", batch_size=500, max_batches=20):
    """Fetch all proxies from Supabase with pagination. Premium and normal tiers
    share the same pool, so both monetag_ok and e2_ok rows are returned."""
    all_proxies = []
    for batch in range(max_batches):
        offset = batch * batch_size
        endpoint = (
            f"/proxy_results?select=ip,port,proto,country,latency_ms"
            f"&or=(monetag_ok.eq.true,e2_ok.eq.true)"
            f"&order=latency_ms.asc"
            f"&limit={batch_size}&offset={offset}"
        )
        resp = supabase_fetch(endpoint)
        if not resp.ok:
            raise RuntimeError(f"Supabase failed: {resp.status_code}")
        batch_data = resp.json()
        if not batch_data:
            break
        all_proxies.extend(batch_data)
        if len(batch_data) < batch_size:
            break
    return all_proxies


def _fetch_state_keys(state, batch_size=1000, max_batches=10):
    """Fetch all state keys (dead/used) with pagination."""
    keys = set()
    for batch in range(max_batches):
        offset = batch * batch_size
        endpoint = (
            f"{STATE_TABLE}?select=ip,port"
            f"&state=eq.{state}"
            f"&expires_at=gt.{datetime.datetime.utcnow().isoformat()}Z"
            f"&limit={batch_size}&offset={offset}"
        )
        try:
            resp = supabase_fetch(endpoint)
            if resp.ok:
                data = resp.json()
                if not data:
                    break
                keys.update({f"{e['ip']}:{e['port']}" for e in data})
                if len(data) < batch_size:
                    break
        except Exception:
            break
    return keys


def _fetch_blacklisted_keys():
    return _fetch_state_keys("dead")


def _fetch_used_keys():
    return _fetch_state_keys("used")


def mark_dead(ip, port, reason=""):
    try:
        supabase_fetch(
            f"/proxy_results?ip=eq.{ip}&port=eq.{port}",
            method="DELETE"
        )
    except Exception:
        pass
    print(f"  [Proxy] DELETED {ip}:{port} from DB ({reason})", file=sys.stderr)
    return True


def mark_proxy_used(ip, port):
    expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=STATE_TTL_HOURS)).isoformat() + "Z"
    data = {"ip": ip, "port": int(port), "state": "used", "expires_at": expires}
    try:
        supabase_fetch(STATE_TABLE, method="POST", data=data)
    except Exception:
        pass
    print(f"  [Proxy] Marked {ip}:{port} as used (skip 24h)", file=sys.stderr)


# ══════════════════════════════════════════════════════════════
#  Geo targeting — Monetag zones count impressions only for the
#  targeted country, so the pool must be restricted to that geo.
# ══════════════════════════════════════════════════════════════

def _target_geo():
    geo = os.environ.get("MONETAG_TARGET_GEO", "")
    if not geo:
        try:
            geo = (config.load() or {}).get("target_geo", "")
        except Exception:
            pass
    return (geo or "").strip().upper()


def resolve_proxy_country(ip, timeout_s=8):
    """Best-effort country code for an IP."""
    for host in (f"http://ipwho.is/{ip}", f"http://ip-api.com/json/{ip}"):
        try:
            r = req_lib.get(host, timeout=timeout_s)
            d = r.json()
            cc = d.get("country_code") or d.get("countryCode") or ""
            if cc:
                return cc.upper()
        except Exception:
            continue
    return ""


def add_proxy(ip, port, proto="http", country="", latency_ms=9999, ok=True):
    """Insert a proxy into the pool (monetag_ok/e2_ok = ok)."""
    if not country:
        country = resolve_proxy_country(ip)
    data = {
        "ip": ip,
        "port": int(port),
        "proto": proto,
        "country": country.upper(),
        "latency_ms": int(latency_ms),
        "monetag_ok": ok,
        "e2_ok": ok,
    }
    resp = supabase_fetch("/proxy_results", method="POST", data=data)
    if resp.ok:
        print(f"  [Proxy] Added {ip}:{port} ({country or 'geo?'})", file=sys.stderr)
    else:
        print(f"  [Proxy] Add failed for {ip}:{port}: HTTP {resp.status_code}", file=sys.stderr)
    return resp.ok


def update_proxy_country(ip, port, country):
    try:
        resp = supabase_fetch(
            f"/proxy_results?ip=eq.{ip}&port=eq.{port}",
            method="PATCH",
            data={"country": country.upper()},
        )
        return resp.ok
    except Exception:
        return False


def sync_proxy_geo(batch_size=200, max_batches=20):
    """Tag any proxies without a country code so geo selection works."""
    all_proxies = fetch_proxies("premium", batch_size=batch_size, max_batches=max_batches)
    untagged = [p for p in all_proxies if not (p.get("country") or "").strip()]
    print(f"  [Proxy] {len(all_proxies)} in pool, {len(untagged)} without country", file=sys.stderr)
    if not untagged:
        return 0
    fixed = 0
    for p in untagged:
        cc = resolve_proxy_country(p["ip"])
        if cc and update_proxy_country(p["ip"], p["port"], cc):
            fixed += 1
        time.sleep(0.05)
    print(f"  [Proxy] Tagged {fixed}/{len(untagged)} with country", file=sys.stderr)
    return fixed


# ══════════════════════════════════════════════════════════════
#  TCP-level tests (fast, parallel, Engine 1)
# ══════════════════════════════════════════════════════════════

def _test_tcp_connect(proxy, timeout_s=2):
    start = time.time()
    try:
        sock = socket.create_connection((proxy["ip"], int(proxy["port"])), timeout=timeout_s)
        sock.close()
        elapsed = int((time.time() - start) * 1000)
        return {"ok": True, "latency_ms": elapsed}
    except Exception:
        return {"ok": False, "latency_ms": int((time.time() - start) * 1000)}


def test_proxy_quick(proxy, timeout_ms=3000):
    tcp = _test_tcp_connect(proxy, timeout_s=2)
    if not tcp["ok"]:
        return tcp
    start = time.time()
    try:
        proxies_dict = {
            "http": f"http://{proxy['ip']}:{proxy['port']}",
            "https": f"http://{proxy['ip']}:{proxy['port']}",
        }
        resp = req_lib.get(TEST_URL, proxies=proxies_dict, timeout=timeout_ms / 1000)
        elapsed = int((time.time() - start) * 1000)
        if resp.ok:
            return {"ok": True, "latency_ms": elapsed}
    except Exception:
        pass
    return {"ok": True, "latency_ms": tcp["latency_ms"]}


# ══════════════════════════════════════════════════════════════
#  Engine 2: Selenium browser validation
# ══════════════════════════════════════════════════════════════

def test_proxy_selenium(proxy, timeout_s=60):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    if proxy.get("username"):
        proxy_url = f"http://{proxy['username']}:{proxy.get('password', '')}@{proxy['ip']}:{proxy['port']}"
    else:
        proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
    start = time.time()
    driver = None
    try:
        options = Options()
        options.add_argument(f"--proxy-server={proxy_url}")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--window-size=1280,720")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
        options.binary_location = _detect_chrome_binary()
        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            chromedriver_path = "/usr/bin/chromedriver"
            if os.path.exists(chromedriver_path) and _check_native_binary(chromedriver_path):
                service = Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

        driver.set_page_load_timeout(30)

        smartlink = os.environ.get("MONETAG_SMARTLINK_URL", "")
        try:
            cfg = config.load()
            if not smartlink:
                smartlink = cfg.get("smartlink_url", "")
        except Exception:
            pass
        test_target = smartlink or TEST_URL

        try:
            driver.get(test_target)
        except Exception:
            pass

        # A proxy is "good" when a real browser through it can reach the
        # offer: either the URL leaves the smartlink domain, or the page
        # actually rendered real content (inline offers stay on the domain).
        left_smartlink = False
        good_page = False
        final_url = ""
        for _ in range(15):
            time.sleep(1)
            try:
                final_url = driver.current_url
            except Exception:
                break
            if "chrome-error" in final_url or "about:blank" in final_url or final_url.startswith("data:"):
                break
            if smartlink and "oclasrv.com" not in final_url and "monetag.com" not in final_url and "omg10.com" not in final_url:
                left_smartlink = True
                break
            try:
                body = driver.find_element("tag name", "body").text or ""
            except Exception:
                body = ""
            if len(body) > 400:
                good_page = True
                break

        is_good = bool(
            final_url
            and "chrome-error" not in final_url
            and "about:blank" not in final_url
            and not final_url.startswith("data:")
            and (left_smartlink or good_page or not smartlink)
        )
        total_ms = int((time.time() - start) * 1000)
        driver.quit()
        driver = None
        return {"ok": is_good, "latency_ms": total_ms, "finalUrl": final_url}

    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        return {"ok": False, "latency_ms": int((time.time() - start) * 1000), "error": str(e)}


# ══════════════════════════════════════════════════════════════
#  Main getProxy: Engine 1 (TCP alive) → Engine 2 (Selenium validate)
# ══════════════════════════════════════════════════════════════


import random


def _ipcook_url():
    """IPCook genips API URL — PRIMARY proxy source. Read from IPCOOK_URL env
    (CI secret) or config ipcook_url. Returns '' when not configured."""
    url = os.environ.get("IPCOOK_URL", "").strip()
    if not url:
        try:
            url = (config.load() or {}).get("ipcook_url", "").strip()
        except Exception:
            url = ""
    return url


def get_ipcook_proxy():
    """Fetch one credentialed proxy from the IPCook dynamic-genips API
    (PRIMARY source). The response is one host:port:user:pass per line; each
    credential rotates residential exit IPs (fresh per connection), so a single
    paste feeds the loop until its bandwidth quota is exhausted.

    Returns {"ip", "port", "proxy", "source": "ipcook"} or None.
    """
    url = _ipcook_url()
    if not url:
        return None
    try:
        resp = req_lib.get(url, timeout=30)
        if not resp.ok:
            print(f"  [IPCook] HTTP {resp.status_code}", file=sys.stderr)
            return None
        text = resp.text or ""
        for line in text.splitlines():
            parts = line.strip().split(":")
            if len(parts) < 4:
                continue
            host, port = parts[0], parts[1]
            user, pw = parts[2], ":".join(parts[3:])
            import urllib.parse
            proxy = f"http://{urllib.parse.quote(user)}:{urllib.parse.quote(pw)}@{host}:{port}"
            print(f"  [IPCook] got {host}:{port} (source=ipcook)", file=sys.stderr)
            return {"ip": host, "port": int(port), "proxy": proxy, "source": "ipcook"}
        print("  [IPCook] no usable lines in response", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  [IPCook] error: {e}", file=sys.stderr)
        return None


def proxy_str(p):
    """String form of a proxy dict for CLI/workflow consumption. IPCook entries
    carry credentials (user:pass@host:port); Supabase entries are plain ip:port.
    No scheme — callers prepend http://."""
    if p and p.get("source") == "ipcook":
        return (p.get("proxy") or "").replace("http://", "").replace("https://", "")
    return f"{p.get('ip')}:{p.get('port')}" if p else ""


def _finalize_proxy(picked, source):
    """Add uniform proxy/source keys to a Supabase pick."""
    if picked is None:
        return None
    picked = dict(picked)
    picked.setdefault("proxy", f"http://{picked['ip']}:{picked['port']}")
    picked.setdefault("source", source)
    return picked


def get_proxy(tier="premium", validate=None):
    """Pick a proxy. IPCook (rotating residential API, credentialed) is the
    PRIMARY source; the Supabase pool is the fallback. `validate=None` honors
    MONETAG_VALIDATE_PROXIES; True/False force/disable the Engine-2 browser
    validation (fast path)."""
    if validate is None:
        validate = os.environ.get("MONETAG_VALIDATE_PROXIES", "1") == "1"

    ipcook = get_ipcook_proxy()
    if ipcook:
        return ipcook

    print("  [Proxy] Fetching proxies from Supabase (unlimited, batched)...", file=sys.stderr)
    all_proxies = fetch_proxies(tier, batch_size=500, max_batches=20)
    print(f"  [Proxy] Found {len(all_proxies)} {tier} proxies in DB (paginated)", file=sys.stderr)
    if not all_proxies:
        return None

    geo = _target_geo()
    if geo:
        geo_proxies = [p for p in all_proxies if (p.get("country") or "").strip().upper() == geo]
        print(f"  [Proxy] Target geo {geo}: {len(geo_proxies)}/{len(all_proxies)} proxies match", file=sys.stderr)
        if not geo_proxies:
            print(f"  [Proxy] ERROR: no {geo} proxies in pool — add {geo} proxies or clear MONETAG_TARGET_GEO", file=sys.stderr)
            return None
        all_proxies = geo_proxies

    print("  [Proxy] Checking used state (Supabase)...", file=sys.stderr)
    used_keys = _fetch_used_keys()
    print(f"  [Proxy] {len(used_keys)} used (24h)", file=sys.stderr)

    filtered = [p for p in all_proxies if f"{p['ip']}:{p['port']}" not in used_keys]
    print(f"  [Proxy] Filtered: {len(filtered)} remaining (skipped {len(all_proxies) - len(filtered)})", file=sys.stderr)

    if not filtered:
        print("  [Proxy] All proxies excluded, trying all...", file=sys.stderr)
        filtered = all_proxies

    random.shuffle(filtered)

    alive = []
    dead = []
    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = {pool.submit(test_proxy_quick, p, 3000): p for p in filtered}
        for f in as_completed(futures):
            p = futures[f]
            try:
                r = f.result()
                if r["ok"]:
                    alive.append({**p, "latency_ms": r["latency_ms"]})
                else:
                    dead.append(p)
            except Exception:
                dead.append(p)

    if dead:
        for p in dead:
            mark_dead(p["ip"], p["port"], "tcp_dead")
        print(f"  [Proxy] Deleted {len(dead)} dead proxies from DB", file=sys.stderr)

    if not alive:
        print("  [Proxy] No alive proxies found", file=sys.stderr)
        return None

    alive.sort(key=lambda p: p.get("latency_ms", 9999))

    if validate:
        picked = _pick_browser_validated(alive)
        if picked is not None:
            return _finalize_proxy(picked, "supabase")
        print("  [Proxy] No proxy passed browser validation; falling back to fastest TCP-alive (views may not count)", file=sys.stderr)

    picked = alive[0]
    print(f"  [Proxy] Selected: {picked['ip']}:{picked['port']} ({picked.get('latency_ms', '?')}ms) [{len(alive)} alive, {len(dead)} deleted]", file=sys.stderr)
    return _finalize_proxy(picked, "supabase")


def _pick_browser_validated(alive, top_n=5, max_workers=3):
    from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac

    try:
        top_n = int(os.environ.get("MONETAG_VALIDATE_TOP", str(top_n)))
    except Exception:
        pass
    try:
        max_workers = int(os.environ.get("MONETAG_VALIDATE_WORKERS", str(max_workers)))
    except Exception:
        pass
    top = alive[:top_n]
    print(f"  [Proxy] Browser-validating top {len(top)} proxies through smartlink (parallel)", file=sys.stderr)
    validated = []
    with _TPE(max_workers=min(len(top), max_workers)) as pool:
        futures = {pool.submit(test_proxy_selenium, p, 30): p for p in top}
        for f in _ac(futures):
            p = futures[f]
            try:
                r = f.result()
                if r.get("ok"):
                    validated.append({**p, "latency_ms": r.get("latency_ms", p.get("latency_ms", 9999))})
                    print(f"  [Proxy] OK: {p['ip']}:{p['port']} -> {r.get('finalUrl', '')}", file=sys.stderr)
                else:
                    print(f"  [Proxy] FAIL: {p['ip']}:{p['port']} -> {r.get('finalUrl', '')}", file=sys.stderr)
            except Exception as e:
                print(f"  [Proxy] ERR: {p['ip']}:{p['port']} ({e})", file=sys.stderr)

    if not validated:
        return None

    validated.sort(key=lambda p: p.get("latency_ms", 9999))
    picked = validated[0]
    print(f"  [Proxy] Browser-validated {len(validated)}/{len(top)}; selected {picked['ip']}:{picked['port']} ({picked.get('latency_ms', '?')}ms)", file=sys.stderr)
    return picked


def get_proxy_quick(tier="premium"):
    return get_proxy(tier, validate=False)


def get_public_ip(timeout_s=10):
    try:
        r = req_lib.get("https://api.ipify.org?format=json", timeout=timeout_s)
        return r.json().get("ip")
    except Exception:
        try:
            r = req_lib.get("https://ifconfig.me/ip", timeout=timeout_s)
            return r.text.strip()
        except Exception:
            return None


def verify_proxy_ip(proxy):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    RED = "\033[31m"
    DIM = "\033[2m"
    NC = "\033[0m"
    check = "\u2713"
    cross = "\u2717"
    warn = "\u26a0"

    print("")
    print(f"{BOLD}  Proxy IP Verification{NC}")
    print(f"  {DIM}{'─' * 22}{NC}")

    print(f"  {CYAN}Fetching direct IP (no proxy)...{NC}")
    real_ip = get_public_ip()
    if real_ip:
        print(f"  {GREEN}{check}{NC} Direct IP: {BOLD}{real_ip}{NC}")
    else:
        print(f"  {YELLOW}{warn}{NC} Could not determine direct IP")

    proxy_url = proxy.get("proxy") or f"http://{proxy['ip']}:{proxy['port']}"
    print(f"  {CYAN}Launching browser via proxy {proxy_str(proxy)}...{NC}")
    driver = None
    try:
        options = Options()
        options.add_argument(f"--proxy-server={proxy_url}")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--window-size=1280,720")
        options.binary_location = _detect_chrome_binary()

        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            chromedriver_path = "/usr/bin/chromedriver"
            if os.path.exists(chromedriver_path) and _check_native_binary(chromedriver_path):
                service = Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

        driver.set_page_load_timeout(15)
        driver.implicitly_wait(10)

        print(f"  {CYAN}Checking browser IP via api.ipify.org...{NC}")
        proxy_ip = None
        try:
            driver.get("https://api.ipify.org?format=json")
            body = driver.find_element("tag name", "body").text
            proxy_ip = json.loads(body).get("ip")
        except Exception:
            try:
                driver.get("https://ifconfig.me/ip")
                proxy_ip = driver.find_element("tag name", "body").text.strip()
            except Exception:
                pass

        driver.quit()
        driver = None

        if not proxy_ip:
            print(f"  {RED}{cross}{NC} Could not determine browser IP — proxy may be blocking")
            return False

        print(f"  {GREEN}{check}{NC} Browser IP: {BOLD}{proxy_ip}{NC}")
        print("")

        if real_ip and proxy_ip == real_ip:
            print(f"  {RED}{cross}{NC} IP match! Proxy {RED}NOT working{NC} — traffic bypassing proxy")
            print(f"  {DIM}  Browser IP ({proxy_ip}) == Direct IP ({real_ip}){NC}")
            return False
        elif real_ip and proxy_ip != real_ip:
            print(f"  {GREEN}{check}{NC} IP differs! Proxy {GREEN}WORKING{NC} — traffic routing through proxy")
            print(f"  {DIM}  Direct: {real_ip} → Proxy: {proxy_ip}{NC}")
            return True
        else:
            print(f"  {YELLOW}{warn}{NC} Proxy responding but direct IP unknown — cannot verify")
            return True
    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print(f"  {RED}{cross}{NC} Browser launch failed: {e}")
        return False


if __name__ == "__main__":
    import argparse

    if "--setup" in sys.argv:
        if not sys.stdin.isatty():
            print("No interactive terminal. Set env vars:", file=sys.stderr)
            print("  SUPABASE_URL=https://... SUPABASE_KEY=... SUPABASE_SECRET=...", file=sys.stderr)
            sys.exit(1)

        BOLD = "\033[1m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
        CYAN = "\033[36m"; RED = "\033[31m"; DIM = "\033[2m"; NC = "\033[0m"
        check = "\u2713"; cross = "\u2717"; warn = "\u26a0"

        cfg = config.load()

        print(f"\n{BOLD}Proxy Setup Wizard{NC}")
        print(f"{DIM}{'─' * 50}{NC}\n")

        # 1. Enable/disable
        current_enabled = cfg.get("proxy_enabled", False)
        default = "y" if current_enabled else "n"
        ans = input(f"Enable proxy rotation? (y/N) [{default}]: ").strip().lower()
        ans = ans or default
        if ans not in ("y", "yes"):
            config.save({"proxy_enabled": False})
            print(f"  {YELLOW}{warn}{NC} Proxy disabled. Re-run {BOLD}monetag proxy --setup{NC} to enable.\n")
            sys.exit(0)

        # 2. Supabase URL
        default_url = "https://bytemjjijgwwcrxlgutf.supabase.co"
        current_url = cfg.get("supabase_url") or default_url
        ans = input(f"Supabase URL [{current_url}]: ").strip()
        sb_url = ans or current_url

        # 3. Supabase Anon Key
        current_key = cfg.get("supabase_key", "")
        key_hint = current_key[:12] + "..." if len(current_key) > 12 else "(not set)"
        ans = input(f"Supabase Anon/Publishable Key [{key_hint}]: ").strip()
        sb_key = ans or current_key

        # 4. Supabase Secret
        current_secret = cfg.get("supabase_secret", "")
        sec_hint = current_secret[:12] + "..." if len(current_secret) > 12 else "(not set)"
        ans = input(f"Supabase Secret/Service Key [{sec_hint}]: ").strip()
        sb_secret = ans or current_secret

        if not sb_key or not sb_secret:
            print(f"  {YELLOW}{warn}{NC} Key or secret missing — saving with proxy disabled.")
            config.save({"supabase_url": sb_url, "supabase_key": sb_key, "supabase_secret": sb_secret, "proxy_enabled": False})
            sys.exit(1)

        # 5. Proxy tier
        current_tier = cfg.get("proxy_tier", "premium")
        ans = input(f"Proxy tier? (normal/premium) [{current_tier}]: ").strip().lower()
        tier = ans or current_tier
        if tier not in ("normal", "premium"):
            print(f"  Invalid tier '{tier}', using 'premium'")
            tier = "premium"

        # 6. Save credentials
        config.save({
            "supabase_url": sb_url,
            "supabase_key": sb_key,
            "supabase_secret": sb_secret,
            "proxy_enabled": True,
            "proxy_tier": tier,
        })
        print(f"  {GREEN}{check}{NC} Credentials saved to ~/.config/monetag/config.json\n")

        # 7. Validate
        print(f"  Validating credentials...", end=" ", flush=True)
        try:
            proxies = fetch_proxies(tier)
            print(f"{GREEN}{check}{NC}")
            print(f"  {GREEN}{check}{NC} {len(proxies)} {tier} proxies in Supabase")
        except Exception as e:
            print(f"{RED}{cross}{NC}")
            print(f"  {RED}{cross}{NC} Validation failed: {e}")
            print(f"  {YELLOW}{warn}{NC} Credentials saved but may be invalid. Check and re-run: {BOLD}monetag proxy --setup{NC}")
            sys.exit(1)

        # 8. Pool health check
        ans = input(f"\n  Run pool health check (test 5 random proxies)? (Y/n): ").strip().lower()
        if ans not in ("n", "no"):
            print(f"\n  Testing random proxies...")
            sample = proxies[:]
            random.shuffle(sample)
            sample = sample[:5]
            alive = 0
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(test_proxy_quick, p, 3000): p for p in sample}
                for f in as_completed(futures):
                    p = futures[f]
                    try:
                        r = f.result()
                        if r.get("ok"):
                            alive += 1
                            print(f"    {GREEN}{check}{NC} {p['ip']}:{p['port']} ({r.get('latency_ms', '?')}ms)")
                        else:
                            print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} (dead)")
                    except Exception as e:
                        print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} (error: {e})")
            print(f"\n  {alive}/{len(sample)} proxies alive")

        print(f"\n{GREEN}{BOLD}Setup complete.{NC} Run {BOLD}monetag{NC} to start.\n")
        sys.exit(0)

    if "--status" in sys.argv:
        cfg = config.load()
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        CYAN = "\033[36m"
        RED = "\033[31m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        NC = "\033[0m"
        check = "\u2713"
        cross = "\u2717"
        warn = "\u26a0"

        print("")
        print(f"{BOLD}  Proxy Status{NC}")
        print(f"  {DIM}{'─' * 11}{NC}")
        print(f"  Enabled: {GREEN if cfg.get('proxy_enabled') else YELLOW}{'yes' if cfg.get('proxy_enabled') else 'no'}{NC}")
        print(f"  Tier:    {cfg.get('proxy_tier', 'premium')}")
        print(f"  URL:     {cfg.get('supabase_url', '')[:40] + '...' if cfg.get('supabase_url') else '(not set)'}")
        print(f"  Key:     {'set' if cfg.get('supabase_key') else '(not set)'}")
        print(f"  Secret:  {'set' if cfg.get('supabase_secret') else '(not set)'}")
        bl = config.load_proxy_blacklist()
        print(f"  Blacklist: {len(bl)} entries")
        print("")
        if not cfg.get("proxy_enabled"):
            print(f"  {YELLOW}{warn}{NC} Proxy disabled. Run {BOLD}monetag proxy --setup{NC} to enable")
            sys.exit(0)
        if not (cfg.get("supabase_url") and cfg.get("supabase_key") and cfg.get("supabase_secret")):
            print(f"  {RED}{cross}{NC} Credentials incomplete. Run {BOLD}monetag proxy --setup{NC}")
            sys.exit(1)
        try:
            proxies = fetch_proxies(cfg.get("proxy_tier", "premium"))
        except Exception as e:
            print(f"  {RED}{cross}{NC} Fetch failed: {e}")
            sys.exit(1)
        print(f"  {GREEN}{check}{NC} {len(proxies)} proxies in DB")
        if not proxies:
            print(f"  {YELLOW}{warn}{NC} Empty pool")
            sys.exit(0)
        sample = proxies[:]
        random.shuffle(sample)
        sample = sample[:5]
        alive = 0
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(test_proxy_quick, p, 3000): p for p in sample}
            for f in as_completed(futures):
                p = futures[f]
                try:
                    r = f.result()
                    if r["ok"]:
                        alive += 1
                        print(f"    {GREEN}{check}{NC} {p['ip']}:{p['port']} ({r['latency_ms']}ms)")
                    else:
                        print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} FAIL")
                except Exception:
                    print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} FAIL")
        print(f"  {GREEN if alive else YELLOW}{check if alive else warn}{NC} {alive}/{len(sample)} alive")
        print("")
        sys.exit(0)

    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not target or ":" not in target:
            print("Usage: --test ip:port", file=sys.stderr)
            sys.exit(1)
        ip, port = target.split(":", 1)
        proxy = {"ip": ip, "port": int(port), "proto": "https"}
        print(f"  [Proxy] Testing {ip}:{port}...", file=sys.stderr)
        qr = test_proxy_quick(proxy, 3000)
        print(f"  [Proxy] TCP: {'PASS' if qr['ok'] else 'FAIL'} ({qr['latency_ms']}ms)", file=sys.stderr)
        if qr["ok"]:
            pr = test_proxy_selenium(proxy, 30)
            print(f"  [Proxy] Selenium: {'PASS' if pr['ok'] else 'FAIL'} ({pr['latency_ms']}ms)", file=sys.stderr)
            if pr["ok"]:
                print(f"{ip}:{port}")
                sys.exit(0)
        sys.exit(1)

    if "--verify-ip" in sys.argv:
        cfg = config.load()
        if not cfg.get("proxy_enabled") or not cfg.get("supabase_key") or not cfg.get("supabase_secret"):
            print("  Proxy not configured. Run: monetag proxy --setup", file=sys.stderr)
            sys.exit(1)
        print("  [Proxy] Getting proxy from pool...", file=sys.stderr)
        proxy = get_proxy(cfg.get("proxy_tier", "premium"))
        if not proxy:
            print("  [Proxy] No proxy available", file=sys.stderr)
            sys.exit(1)
        print(f"  [Proxy] Got: {proxy['ip']}:{proxy['port']}", file=sys.stderr)
        ok = verify_proxy_ip(proxy)
        sys.exit(0 if ok else 1)

    if "--sync-geo" in sys.argv:
        sync_proxy_geo()
        sys.exit(0)

    if "--import" in sys.argv:
        idx = sys.argv.index("--import")
        if idx + 1 >= len(sys.argv):
            print("Usage: --import ip:port[:proto] ip:port ...", file=sys.stderr)
            sys.exit(1)
        n_added = 0
        for raw in sys.argv[idx + 1:]:
            try:
                if raw.count(":") == 1:
                    ip, port = raw.split(":", 1)
                    proto = "http"
                else:
                    ip, port, proto = raw.rsplit(":", 2)
                if add_proxy(ip.strip(), int(port), proto):
                    n_added += 1
            except Exception as e:
                print(f"  [Proxy] skip {raw}: {e}", file=sys.stderr)
        print(f"  [Proxy] Imported {n_added} proxies", file=sys.stderr)
        sys.exit(0 if n_added else 1)

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Monetag Proxy Rotator")
        print()
        print("Usage:")
        print("  python3 proxy_rotator.py --setup         Interactive setup wizard")
        print("  python3 proxy_rotator.py --status        Pool health & config status")
        print("  python3 proxy_rotator.py --quick [tier]   Get one proxy (stdout)")
        print("  python3 proxy_rotator.py [tier]          Get proxy (verbose)")
        print("  python3 proxy_rotator.py --test ip:port  Test specific proxy")
        print("  python3 proxy_rotator.py --import ip:port ...   Add proxies to pool")
        print("  python3 proxy_rotator.py --sync-geo      Tag untagged proxies with country")
        print()
        print("Geo targeting: set MONETAG_TARGET_GEO (e.g. IN) or config target_geo")
        print("Tiers: premium (default), normal")
        print("Config: ~/.config/monetag/config.json")
        sys.exit(0)

    if "--quick" in sys.argv:
        tier = "premium"
        for a in sys.argv[1:]:
            if not a.startswith("-"):
                tier = a
                break
        p = get_proxy_quick(tier)
        if p:
            print(proxy_str(p))
            sys.exit(0)
        sys.exit(1)

    tier = "premium"
    for a in sys.argv[1:]:
        if not a.startswith("-"):
            tier = a
            break
    try:
        p = get_proxy(tier)
        if p:
            print(proxy_str(p))
            sys.exit(0)
        sys.exit(1)
    except Exception as e:
        print(f"  [Proxy] Error: {e}", file=sys.stderr)
        sys.exit(1)
