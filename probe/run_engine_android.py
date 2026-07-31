#!/usr/bin/env python3
"""Run the monetag engine against the emulator's REAL Chrome via Appium
(MONETAG_ANDROID=1) with residential proxies from the Supabase pool.

Owns the proxy acquisition + retry logic because the android-emulator-runner
action executes its `script:` lines one-by-one (no for/if blocks) — all
decisions live here in Python. Engine-2 browser validation is tolerated but
falls back to TCP-alive when no desktop browser exists on the runner; the real
Android Chrome is the ultimate validation anyway.

Writes view_report.json (by the engine) + run_status.txt (read by the workflow
summary/relay steps).
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SMARTLINK = os.environ.get("MONETAG_SMARTLINK_URL", "").strip()
VIEWS = os.environ.get("MONETAG_VIEWS", "3")
VERIFY = os.environ.get("MONETAG_VERIFY_MODE", "strict")
TS = os.environ.get("MONETAG_TRAFFIC_SOURCE", "youtube")

os.environ["MONETAG_ANDROID"] = "1"
os.environ["MONETAG_ROTATE_MODE"] = "fast"

from proxy_rotator import get_proxy  # noqa: E402


def get_verified():
    try:
        with open("view_report.json") as f:
            r = json.load(f)
        return int(r["summary"].get("verified_or_likely", 0))
    except Exception:
        return 0


def run_engine(proxy):
    proxy_url = proxy.get("proxy") or f"http://{proxy['ip']}:{proxy['port']}"
    os.environ["MONETAG_PROXY"] = proxy_url
    print(f"=== ENGINE (android) proxy={proxy_url} source={proxy.get('source')} ===", flush=True)
    t0 = time.time()
    try:
        subprocess.run([
            sys.executable, "monetag_automation.py", SMARTLINK,
            "--views", VIEWS, "--verify-mode", VERIFY, "--traffic-source", TS,
        ], timeout=420, check=False)
    except subprocess.TimeoutExpired:
        print("ENGINE_TIMEOUT", flush=True)
    print(f"engine elapsed={time.time() - t0:.0f}s", flush=True)


def main():
    if not SMARTLINK:
        print("ERROR: MONETAG_SMARTLINK_URL empty", flush=True)
        sys.exit(2)
    target = int(VIEWS)
    for attempt in range(1, 3):
        if get_verified() >= target:
            print(f"already verified: {get_verified()}/{target} views — done", flush=True)
            break
        print(f"=== proxy acquisition attempt {attempt}/2 ===", flush=True)
        proxy = get_proxy("premium", validate=True)
        if not proxy:
            print("ERROR: no proxy from pool", flush=True)
            sys.exit(2)
        run_engine(proxy)
        v = get_verified()
        print(f"verified_or_likely={v}", flush=True)
        if v >= target:
            break
    with open("run_status.txt", "w") as f:
        f.write(f"verified={get_verified()}")
    sys.exit(0)


if __name__ == "__main__":
    main()
