#!/usr/bin/env python3
import subprocess, threading, http.server, time, os, re

OUT = "evidence/ua_capture.txt"
HDRS = ("user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        "sec-ch-ua-arch", "sec-ch-ua-platform-version", "sec-ch-ua-model",
        "x-requested-with", "accept-language", "x-forwarded-for")


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
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def sh(*args):
    subprocess.run(args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


httpd = http.server.HTTPServer(("127.0.0.1", 8888), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

sh("adb", "reverse", "tcp:8888", "tcp:8888")
time.sleep(1)
sh("adb", "shell", "am", "start", "-a", "android.intent.action.VIEW",
   "-d", "http://127.0.0.1:8888/ua")
time.sleep(10)
with open("evidence/ua_screen.png", "wb") as f:
    subprocess.run(["adb", "exec-out", "screencap", "-p"], check=False,
                   stdout=f, stderr=subprocess.DEVNULL)
httpd.shutdown()

print("--- UA CAPTURE ---")
try:
    with open(OUT) as f:
        print(f.read())
except FileNotFoundError:
    print("no UA captured")
