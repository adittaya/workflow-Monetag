#!/usr/bin/env python3
"""Prove selenium webdriver.Remote -> Appium UiAutomator2 -> real Chrome on the
emulator: load a URL served on the host (adb reverse), read the real UA/UA-CH,
verify element interaction works. No proxy — just the drive test.
"""
import subprocess, threading, http.server, time, os, json, sys, shutil, glob

OUT = "evidence/appium_ua_capture.txt"
HDRS = ("user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        "sec-ch-ua-arch", "sec-ch-ua-platform-version", "sec-ch-ua-model",
        "accept-language", "x-requested-with")


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        os.makedirs("evidence", exist_ok=True)
        with open(OUT, "a") as f:
            f.write("PATH=" + self.path + "\n")
            for k, v in self.headers.items():
                if k.lower() in HDRS:
                    f.write(f"{k}: {v}\n")
            f.write("---\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body><h1 id=ok>ok</h1></body></html>")

    def log_message(self, *a):
        pass


httpd = http.server.HTTPServer(("127.0.0.1", 8888), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
except ImportError:
    print("DRIVE=FAIL selenium not installed")
    sys.exit(1)

opts = webdriver.ChromeOptions()
opts.set_capability("platformName", "Android")
opts.set_capability("appium:deviceName", "emulator-5554")
opts.set_capability("browserName", "Chrome")
opts.set_capability("appium:automationName", "UiAutomator2")
opts.set_capability("appium:noReset", True)
opts.set_capability("appium:adbExecTimeout", 60000)
_cd = shutil.which("chromedriver") or glob.glob("/usr/local/lib/node_modules/chromedriver/lib/chromedriver/chromedriver")
if _cd:
    opts.set_capability("appium:chromedriverExecutable", _cd if isinstance(_cd, str) else _cd[0])
    print("CHROMEDRIVER:", _cd)
else:
    opts.set_capability("appium:chromedriverAutodownload", True)
    print("CHROMEDRIVER: autodownload")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_argument("--no-first-run")

driver = None
try:
    driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=opts)
    print("DRIVE=connected")
    driver.get("http://127.0.0.1:8888/ua")
    time.sleep(4)
    title = driver.title
    ua = driver.execute_script("return navigator.userAgent")
    uach = driver.execute_script("return JSON.stringify(navigator.userAgentData)")
    plat = driver.execute_script("return navigator.platform")
    w = driver.get_window_size()
    print("TITLE:", title)
    print("UA:", ua)
    print("UA-CH:", uach)
    print("PLATFORM:", plat)
    print("WINDOW:", w)
    els = driver.find_elements(By.ID, "ok")
    print("ELEMENTS_FOUND:", len(els))
    driver.save_screenshot("evidence/appium_drive.png")
    print("DRIVE=OK")
except Exception as e:
    import traceback
    traceback.print_exc()
    print("DRIVE=FAIL", repr(e))
finally:
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    httpd.shutdown()
