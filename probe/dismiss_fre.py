#!/usr/bin/env python3
"""Ensure Chrome's FirstRunActivity (FRE) is dismissed on a fresh emulator.

Strategy (tried in order):
1. adb root + write /data/local/tmp/chrome-command-line with
   --disable-fre --no-first-run (works on userdebug images), force-stop
   Chrome, then launch it to trigger/verify.
2. If FRE still shows, UI tap-through: uiautomator dumps -> tap
   Accept & continue / No thanks / ... buttons until
   ChromeTabbedActivity resumes.

Writes probe/evidence/fre_dump_N.xml for debugging.
"""
import subprocess, re, time, os, sys, shutil

TARGETS = ("accept & continue", "continue", "no thanks", "get started", "skip",
           "i agree", "next", "ok", "got it", "not now", "close")

UATARGET = "com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity"
FREACT = "org.chromium.chrome.browser.firstrun.FirstRunActivity"
URL = "http://127.0.0.1:8888/ua"


def sh(*args, text=False, timeout=90, capture=True):
    return subprocess.run(args, check=False, capture_output=capture, text=text, timeout=timeout)


def current_activity():
    r = sh("adb", "shell", "dumpsys", "activity", "activities", text=True)
    m = re.search(r"ResumedActivity: ActivityRecord\{[^ ]* u0 ([^ }]+)", r.stdout)
    return m.group(1) if m else "?"


def fre_active():
    return "FirstRunActivity" in current_activity()


def install_command_line():
    sh("adb", "root")
    time.sleep(2)
    sh("adb", "wait-for-device")
    time.sleep(1)
    sh("adb", "shell",
       "echo '_ --disable-fre --no-first-run --disable-sync' > /data/local/tmp/chrome-command-line")
    sh("adb", "shell", "chmod", "644", "/data/local/tmp/chrome-command-line")
    sh("adb", "shell", "am", "force-stop", "com.android.chrome")


def dump_xml(n):
    sh("adb", "shell", "uiautomator", "dump", f"/sdcard/ui{n}.xml", timeout=30)
    r = sh("adb", "shell", "cat", f"/sdcard/ui{n}.xml", text=True, timeout=30)
    os.makedirs("evidence", exist_ok=True)
    with open(f"evidence/fre_dump_{n}.xml", "w") as f:
        f.write(r.stdout)
    return r.stdout


def bounds_center(node):
    m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def find_tap(xml):
    best = None
    for n in re.findall(r"<node[^>]*/>", xml):
        text = (re.search(r'text="([^"]*)"', n) or [None, ""])[1].lower()
        desc = (re.search(r'content-desc="([^"]*)"', n) or [None, ""])[1].lower()
        if any(t in text or t in desc for t in TARGETS):
            c = bounds_center(n)
            if c and c != (0, 0):
                x1, y1, x2, y2 = map(int, re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n).groups())
                w = x2 - x1
                if best is None or w > best[1]:
                    best = (c, w)
    return best


def tap_through_fre():
    for i in range(15):
        act = current_activity()
        print(f"[fre] attempt {i + 1} activity: {act}")
        if "ChromeTabbedActivity" in act:
            print("[fre] first run dismissed — ChromeTabbedActivity resumed")
            return True
        if "FirstRunActivity" not in act:
            print(f"[fre] not on FirstRunActivity ({act})")
            sh("adb", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", URL)
            time.sleep(5)
        xml = dump_xml(i)
        hit = find_tap(xml)
        if not hit:
            print("[fre] no target button, sending keyevent 4 (back)")
            sh("adb", "shell", "input", "keyevent", "4")
        else:
            (x, y), w = hit
            print(f"[fre] tapping ({x},{y}) width {w}")
            sh("adb", "shell", "input", "tap", str(x), str(y))
        time.sleep(4)
    return False


def main():
    print("[fre] installing chrome-command-line (--disable-fre)")
    install_command_line()
    print("[fre] launching chrome to trigger/verify FRE")
    sh("adb", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", URL)
    time.sleep(8)
    if not fre_active():
        print("[fre] no FRE after command-line install")
    if tap_through_fre():
        return 0
    print("[fre] WARNING: FRE not dismissed — Chrome may be unusable this run")
    return 1


if __name__ == "__main__":
    sys.exit(main())
