#!/usr/bin/env python3
"""Open the real Monetag SmartLink through Appium-driven real Chrome on the
emulator. No proxy yet — proves the redirect chain + landing works on real
Android Chrome. Captures final URL, title, body size, screenshot.
"""
import os, time, sys, traceback

url = os.environ.get("MONETAG_SMARTLINK_URL", "").strip()
if not url:
    print("SL=SKIP no MONETAG_SMARTLINK_URL")
    sys.exit(0)

try:
    from selenium import webdriver
except ImportError:
    print("SL=FAIL selenium not installed")
    sys.exit(1)

opts = webdriver.ChromeOptions()
opts.set_capability("platformName", "Android")
opts.set_capability("appium:deviceName", "emulator-5554")
opts.set_capability("browserName", "Chrome")
opts.set_capability("appium:automationName", "UiAutomator2")
opts.set_capability("appium:noReset", True)
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_argument("--no-first-run")

driver = None
try:
    driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=opts)
    print("SL=connected")
    driver.get(url)
    for i in range(14):
        time.sleep(5)
        cur = driver.current_url or ""
        print(f"[sl] t={i * 5}s url={cur}")
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
    driver.save_screenshot("evidence/appium_smartlink.png")
    print("SL=OK")
except Exception as e:
    traceback.print_exc()
    print("SL=FAIL", repr(e))
finally:
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
