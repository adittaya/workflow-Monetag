#!/usr/bin/env python3
import subprocess, os, time

url = os.environ.get("MONETAG_SMARTLINK_URL", "").strip()
os.makedirs("evidence", exist_ok=True)


def sh(*args, out=None, text=False):
    if out:
        with open(out, "wb") as f:
            subprocess.run(args, check=False, stdout=f, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(args, check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


if url:
    print("smartlink:", url)
    sh("adb", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url)
    time.sleep(30)
    sh("adb", "exec-out", "screencap", "-p", out="evidence/smartlink_1.png")
    with open("evidence/activities.txt", "w") as f:
        subprocess.run(["adb", "shell", "dumpsys", "activity", "activities"],
                       check=False, stdout=f, stderr=subprocess.DEVNULL)
    print("smartlink opened (30s dwell), screencap + activities dumped")
else:
    print("MONETAG_SMARTLINK_URL secret not set — skipping smartlink open")
