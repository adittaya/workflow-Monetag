#!/usr/bin/env python3
"""Fetch ONE residential proxy from the Supabase pool and run the proxy probe
against the emulator's real Chrome (probe/android_proxy.py).

All-in-one because the android-emulator-runner action executes its `script:`
lines one-by-one via /usr/bin/sh -c — shell variables and if/fi blocks do NOT
persist between lines, so any multi-step logic must live in Python.
"""
import os
import subprocess
import sys

from proxy_rotator import get_proxy


def main():
    proxy = get_proxy("premium", validate=False)
    if not proxy:
        print("::warning::No proxy from pool — cannot validate proxy path")
        sys.exit(0)
    ip, port = proxy["ip"], proxy["port"]
    print(f"PROXY={ip}:{port}")
    env = dict(os.environ)
    env["MONETAG_PROXY"] = f"http://{ip}:{port}"
    try:
        subprocess.run([sys.executable, "probe/android_proxy.py"], env=env, check=False)
    except Exception as e:  # noqa: BLE001
        print("PROBE_RUN_FAIL", repr(e))


if __name__ == "__main__":
    main()
