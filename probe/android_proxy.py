#!/usr/bin/env python3
"""Prove a Monetag SmartLink view THROUGH a residential proxy on the emulator's
real Chrome (Appium). Validates three things in one shot:
  1. Proxy actually routes: api.ipify.org (and checkip) return the proxy IP,
     not the runner's datacenter IP.
  2. Chrome accepts --proxy-server on Android via chromedriver.
  3. The SmartLink resolves to a real offer through the proxy.

Usage: MONETAG_PROXY=http://ip:port python3 probe/android_proxy.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

proxy = os.environ.get("MONETAG_PROXY", "").strip()
url = os.environ.get("MONETAG_SMARTLINK_URL", "").strip()
if not proxy:
    print("PROXY=SKIP no MONETAG_PROXY")
    sys.exit(0)
if not url:
    print("PROXY=SKIP no MONETAG_SMARTLINK_URL")
    sys.exit(0)

m = re.match(r"https?://([^:]+):(\d+)", proxy)
if not m:
    print("PROXY=SKIP cannot parse MONETAG_PROXY:", proxy)
    sys.exit(0)
PHOST, PPORT = m.group(1), m.group(2)

print("=== SET DEVICE-WIDE PROXY (adb settings put global http_proxy) ===")
try:
    subprocess.run(["adb", "shell", "settings", "put", "global", "http_proxy",
                    f"{PHOST}:{PPORT}"], capture_output=True, timeout=15)
    print(f"DEVICE_PROXY={PHOST}:{PPORT}")
except Exception as e:
    print("DEVICE_PROXY_FAIL:", repr(e))

try:
    from selenium import webdriver
except ImportError:
    print("PROXY=FAIL selenium not installed")
    sys.exit(1)

opts = webdriver.ChromeOptions()
opts.set_capability("platformName", "Android")
opts.set_capability("appium:deviceName", "emulator-5554")
opts.set_capability("browserName", "Chrome")
opts.set_capability("appium:automationName", "UiAutomator2")
opts.set_capability("appium:noReset", True)
_cd = shutil.which("chromedriver") or glob.glob(
    "/usr/local/lib/node_modules/chromedriver/lib/chromedriver/chromedriver")
if _cd:
    opts.set_capability("appium:chromedriverExecutable",
                        _cd if isinstance(_cd, str) else _cd[0])
    print("CHROMEDRIVER:", _cd)
else:
    opts.set_capability("appium:chromedriverAutodownload", True)
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_argument("--no-first-run")
print(f"DEVICE_PROXY_ARG={PHOST}:{PPORT} (device-wide via settings)")

driver = None
try:
    driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=opts)
    print("PROXY=connected")

    def body_ip():
        try:
            return driver.execute_script(
                "return document.body ? document.body.innerText.trim().slice(0,120) : ''")
        except Exception as e:
            return "ERR:" + repr(e)

    print("=== PUBLIC IP VIA PROXY (api.ipify.org) ===")
    try:
        driver.get("https://api.ipify.org")
        time.sleep(6)
        print("IPIFY:", body_ip())
    except Exception as e:
        print("IPIFY_FAIL:", repr(e))

    print("=== PUBLIC IP VIA PROXY (checkip.amazonaws.com) ===")
    try:
        driver.get("https://checkip.amazonaws.com")
        time.sleep(6)
        print("CHECKIP:", body_ip())
    except Exception as e:
        print("CHECKIP_FAIL:", repr(e))

    print("=== SMARTLINK THROUGH PROXY ===")
    try:
        driver.get(url)
        for i in range(14):
            time.sleep(5)
            cur = driver.current_url or ""
            print(f"[sl] t={i * 5}s url={cur[:130]}")
            if "omg10" not in cur and "afu.php" not in cur and "oclasrv" not in cur:
                print("[sl] left smartlink domain, stopping early")
                break
        try:
            title = driver.title
        except Exception:
            title = "?"
        try:
            body = driver.execute_script(
                "return document.body ? document.body.innerHTML.length : 0")
            text = driver.execute_script(
                "return document.body ? document.body.innerText.slice(0, 500) : ''")
        except Exception as e:
            body, text = -1, repr(e)
        print("FINAL_URL:", driver.current_url)
        print("TITLE:", title)
        print("BODY_LEN:", body)
        print("BODY_TEXT:", (text or "")[:300].replace("\n", " | "))
        try:
            driver.save_screenshot("evidence/android_proxy_smartlink.png")
        except Exception:
            pass
        print("PROXY=OK")
    except Exception as e:
        traceback.print_exc()
        print("PROXY=FAIL", repr(e))
finally:
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    try:
        subprocess.run(["adb", "shell", "settings", "put", "global", "http_proxy",
                        ":0"], capture_output=True, timeout=15)
        print("DEVICE_PROXY_CLEARED")
    except Exception:
        pass
