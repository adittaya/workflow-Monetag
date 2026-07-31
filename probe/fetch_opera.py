#!/usr/bin/env python3
"""Reference-only: download + install Opera x86_64 from APKMirror (verified
2026-07-31). Not used by the probe anymore because the API 35 google_apis
image ships real Chrome (com.android.chrome). Kept for when a second
Android browser is needed.

Chain: app page -> latest release -> x86_64 variant page -> #download-link
(/wp-content/themes/APKMirror/download.php?id=<id>&key=<key>) -> 302 ->
Cloudflare R2 signed .apkm (ZIP of base+splits, 1h expiry) -> unzip ->
adb install-multiple.
"""
import urllib.request, urllib.error, re, time, os, zipfile, sys, subprocess

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=25).read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(6)
                continue
            raise
    raise RuntimeError("too many retries")


def main():
    html = get("https://www.apkmirror.com/apk/opera-software-asa/opera/")
    rels = [r for r in dict.fromkeys(re.findall(r'href="(/apk/opera-software-asa/opera/[^"]*release/)"', html)) if "disqus" not in r]
    if not rels:
        print("OPERAINSTALL=FAIL no release page")
        sys.exit(1)
    rel = rels[0]
    print("release:", rel)
    dl = get("https://www.apkmirror.com" + rel)
    dlp = [r for r in dict.fromkeys(re.findall(r'href="(/apk/opera-software-asa/opera/[^"]*android-apk-download/)"', dl)) if "disqus" not in r]
    dlink = None
    for d in dlp:
        var = get("https://www.apkmirror.com" + d)
        h = re.search(r"<h1[^>]*>(.*?)</h1>", var, re.S)
        title = re.sub(r"<[^>]+>", "", h.group(1)).strip() if h else "?"
        if "x86_64" in title:
            print("variant:", title)
            m = re.search(r'href="(/wp-content/themes/APKMirror/download\.php\?id=\d+&key=[^"]+)"', var)
            if m:
                dlink = m.group(1)
            break
        time.sleep(1.5)
    if not dlink:
        print("OPERAINSTALL=FAIL no x86_64 variant")
        sys.exit(1)
    os.makedirs("probe", exist_ok=True)
    req = urllib.request.Request("https://www.apkmirror.com" + dlink.replace("&amp;", "&"), headers=H)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    with open("probe/opera.apkm", "wb") as f:
        f.write(data)
    print("bundle bytes:", len(data))
    with zipfile.ZipFile("probe/opera.apkm") as z:
        z.extractall("probe/opera_split")
    apks = sorted(f for f in os.listdir("probe/opera_split") if f.endswith(".apk"))
    print("split apks:", apks)
    with open("probe/opera_apks.txt", "w") as f:
        f.write("\n".join(apks))
    r = subprocess.run(["adb", "install-multiple"] + ["probe/opera_split/" + a for a in apks], capture_output=True, text=True)
    print("install rc:", r.returncode, r.stdout[-200:], r.stderr[-200:])
    subprocess.run(["adb", "shell", "pm", "list", "packages"], check=False, text=True)


if __name__ == "__main__":
    main()
