#!/usr/bin/env python3
"""Dismiss Chrome's FirstRunActivity (FRE) wizard on a fresh emulator by
tapping through the known buttons via uiautomator dumps. Chrome blocks all
navigation until FRE is completed, so this must run before any URL is loaded.
"""
import subprocess, re, time, os, sys

TARGETS = ("accept & continue", "continue", "no thanks", "get started", "skip",
           "i agree", "next", "ok", "got it", "not now", "close")

EMPTY_XML = re.compile(r"<node[^>]*resource-id=\"\"[^>]*bounds=\"\[0,0\]\[0,0\]\".*?/>")

def sh(*args, text=False, timeout=60):
    return subprocess.run(args, check=False, capture_output=True, text=text, timeout=timeout)

def dump_xml():
    sh("adb", "shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=30)
    r = sh("adb", "shell", "cat", "/sdcard/ui.xml", text=True, timeout=30)
    return r.stdout

def bounds_center(node):
    m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def find_tap(xml):
    nodes = re.findall(r"<node[^>]*/>", xml)
    best = None
    for n in nodes:
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

def current_activity():
    r = sh("adb", "shell", "dumpsys", "activity", "activities", text=True, timeout=30)
    m = re.search(r"ResumedActivity: ActivityRecord\{[^ ]* u0 ([^ ]+)/([^ }]+)", r.stdout)
    return f"{m.group(1)}/{m.group(2)}" if m else "?"

def main():
    target = "org.chromium.chrome.browser.firstrun.FirstRunActivity"
    for i in range(12):
        act = current_activity()
        print(f"[fre] attempt {i + 1} activity: {act}")
        if "ChromeTabbedActivity" in act:
            print("[fre] first run dismissed — ChromeTabbedActivity resumed")
            return 0
        if "FirstRunActivity" not in act:
            print(f"[fre] not on FirstRunActivity ({act}), tapping anyway")
        xml = dump_xml()
        hit = find_tap(xml)
        if not hit:
            print("[fre] no target button found in UI dump, trying keyevent 4 (back)")
            sh("adb", "shell", "input", "keyevent", "4")
        else:
            (x, y), w = hit
            print(f"[fre] tapping button at ({x},{y}) width {w}")
            sh("adb", "shell", "input", "tap", str(x), str(y))
        time.sleep(4)
    print("[fre] WARNING: FRE not dismissed after 12 attempts")
    return 1

if __name__ == "__main__":
    sys.exit(main())
