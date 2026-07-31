import random
import json
import sys

# ─── Android devices — coherent UA ↔ viewport ↔ dpr ↔ GPU ↔ platform ─────────
# Each device is a complete, internally-consistent fingerprint bundle. Picking a
# device picks ALL of its attributes together so nothing diverges (a mobile UA
# never pairs with a desktop GPU string, wrong viewport, or wrong touch config).
# 122 real devices across brands/price tiers — every view picks a different one
# so Monetag sees a rotating fleet of genuine Android hardware fingerprints.

_ANR = lambda r: ("ANGLE (ARM, " + r + ", OpenGL ES 3.2 ANGLE (ARM, " + r + ", OpenGL ES 3.2))")
_ANQ = lambda r: ("ANGLE (Qualcomm, Adreno (TM) " + r + ", OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) " + r + ", OpenGL ES 3.2))")
_ANX = lambda r: ("ANGLE (ARM, Samsung " + r + ", OpenGL ES 3.2 ANGLE (ARM, Samsung " + r + ", OpenGL ES 3.2))")


def _adb(name, ua, w, h, avail, dpr, gpu_vendor, gpu_renderer, hw=8, mem=8, touch=10):
    return {
        "name": name,
        "ua": ua,
        "viewport": {"width": w, "height": h},
        "screen": {"width": w, "height": h, "availWidth": w, "availHeight": avail},
        "dpr": dpr, "touch": True, "maxTouchPoints": touch,
        "platform": "Linux armv8l",
        "webgl": {"vendor": gpu_vendor, "renderer": gpu_renderer},
        "hw": hw, "mem": mem,
    }


ANDROID_DEVICES = [
    # ── Google Pixel ────────────────────────────────────────────────────────────
    _adb("Google Pixel 9 Pro", "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro Build/AP4A.250505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 8),
    _adb("Google Pixel 8a", "Mozilla/5.0 (Linux; Android 15; Pixel 8a Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 360, 780, 717, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 8),
    _adb("Google Pixel 9", "Mozilla/5.0 (Linux; Android 15; Pixel 9 Build/AP4A.250505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 12),
    _adb("Google Pixel 9 Pro XL", "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro XL Build/AP4A.250505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 3.5, "Google Inc. (ARM)", _ANR("Mali-G715"), 12, 16),
    _adb("Google Pixel 9 Pro Fold", "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro Fold Build/AP4A.250505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 891, 830, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 12, 16),
    _adb("Google Pixel 8", "Mozilla/5.0 (Linux; Android 15; Pixel 8 Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 8),
    _adb("Google Pixel 8 Pro", "Mozilla/5.0 (Linux; Android 15; Pixel 8 Pro Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G715"), 12, 12),
    _adb("Google Pixel 7", "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G710"), 8, 8),
    _adb("Google Pixel 7 Pro", "Mozilla/5.0 (Linux; Android 14; Pixel 7 Pro Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 3.5, "Google Inc. (ARM)", _ANR("Mali-G710"), 12, 12),
    _adb("Google Pixel 7a", "Mozilla/5.0 (Linux; Android 14; Pixel 7a Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G710"), 8, 8),
    _adb("Google Pixel 6", "Mozilla/5.0 (Linux; Android 13; Pixel 6 Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G78"), 8, 8),
    _adb("Google Pixel 6 Pro", "Mozilla/5.0 (Linux; Android 13; Pixel 6 Pro Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 839, 3.5, "Google Inc. (ARM)", _ANR("Mali-G78"), 12, 12),
    _adb("Google Pixel 5", "Mozilla/5.0 (Linux; Android 12; Pixel 5 Build/SP1A.210812.016) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 780, 2.75, "Google Inc. (Qualcomm)", _ANQ("620"), 8, 8),
    # ── Samsung Galaxy S ────────────────────────────────────────────────────────
    _adb("Samsung Galaxy S25 Ultra", "Mozilla/5.0 (Linux; Android 15; SM-S938B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("830"), 8, 12),
    _adb("Samsung Galaxy S25", "Mozilla/5.0 (Linux; Android 15; SM-S931B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("830"), 12, 12),
    _adb("Samsung Galaxy S25+", "Mozilla/5.0 (Linux; Android 15; SM-S936B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("830"), 12, 12),
    _adb("Samsung Galaxy S24", "Mozilla/5.0 (Linux; Android 14; SM-S921B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (ARM)", _ANX("Xclipse 940"), 8, 8),
    _adb("Samsung Galaxy S24+", "Mozilla/5.0 (Linux; Android 14; SM-S926B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("Samsung Galaxy S24 Ultra", "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("Samsung Galaxy S24 FE", "Mozilla/5.0 (Linux; Android 14; SM-S721B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (ARM)", _ANX("Xclipse 940"), 8, 8),
    _adb("Samsung Galaxy S23", "Mozilla/5.0 (Linux; Android 14; SM-S911B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 8),
    _adb("Samsung Galaxy S23 Ultra", "Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 12),
    _adb("Samsung Galaxy S23 FE", "Mozilla/5.0 (Linux; Android 14; SM-S711B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (ARM)", _ANX("Xclipse 920"), 8, 8),
    _adb("Samsung Galaxy S22", "Mozilla/5.0 (Linux; Android 13; SM-S901B Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 8),
    _adb("Samsung Galaxy S21", "Mozilla/5.0 (Linux; Android 13; SM-G991B Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("660"), 8, 8),
    _adb("Samsung Galaxy S21 FE", "Mozilla/5.0 (Linux; Android 13; SM-G990B Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("660"), 8, 8),
    # ── Samsung Galaxy A / M (budget-mid) ───────────────────────────────────────
    _adb("Samsung Galaxy A56", "Mozilla/5.0 (Linux; Android 15; SM-A566B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 2.75, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 8),
    _adb("Samsung Galaxy A36", "Mozilla/5.0 (Linux; Android 15; SM-A366B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (Qualcomm)", _ANQ("620"), 8, 8),
    _adb("Samsung Galaxy A55", "Mozilla/5.0 (Linux; Android 14; SM-A556B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 360, 780, 709, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 8, 8),
    _adb("Samsung Galaxy A35", "Mozilla/5.0 (Linux; Android 14; SM-A356B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 2.625, "Google Inc. (ARM)", _ANR("Mali-G68"), 8, 6),
    _adb("Samsung Galaxy A34", "Mozilla/5.0 (Linux; Android 13; SM-A346B Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 2.625, "Google Inc. (ARM)", _ANR("Mali-G68"), 8, 6),
    _adb("Samsung Galaxy A16", "Mozilla/5.0 (Linux; Android 14; SM-A165F Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Samsung Galaxy A15", "Mozilla/5.0 (Linux; Android 14; SM-A155F Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 4, 4),
    _adb("Samsung Galaxy A14", "Mozilla/5.0 (Linux; Android 13; SM-A145F Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 800, 730, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 4, 4),
    _adb("Samsung Galaxy A05", "Mozilla/5.0 (Linux; Android 13; SM-A055F Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 800, 730, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Samsung Galaxy M35", "Mozilla/5.0 (Linux; Android 14; SM-M356B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 8, 6),
    _adb("Samsung Galaxy M15", "Mozilla/5.0 (Linux; Android 14; SM-M155F Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 4, 4),
    # ── Samsung Z Fold / Flip ───────────────────────────────────────────────────
    _adb("Samsung Galaxy Z Fold 6", "Mozilla/5.0 (Linux; Android 14; SM-F956B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 897, 825, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("Samsung Galaxy Z Flip 6", "Mozilla/5.0 (Linux; Android 14; SM-F741B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("Samsung Galaxy Z Fold 5", "Mozilla/5.0 (Linux; Android 14; SM-F946B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 897, 825, 3.5, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 12),
    _adb("Samsung Galaxy Z Flip 5", "Mozilla/5.0 (Linux; Android 14; SM-F731B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 8),
    # ── Xiaomi / Redmi / POCO ───────────────────────────────────────────────────
    _adb("Xiaomi 15 Pro", "Mozilla/5.0 (Linux; Android 15; 25032RP21G Build/AQ3A.250515.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("830"), 8, 12),
    _adb("Xiaomi 15", "Mozilla/5.0 (Linux; Android 15; 25122PNJ7C Build/AQ3A.250515.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Xiaomi 14", "Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Xiaomi 14 Ultra", "Mozilla/5.0 (Linux; Android 14; 24031DPC20 Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 839, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 16),
    _adb("Xiaomi 13", "Mozilla/5.0 (Linux; Android 14; 2211133C Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 8),
    _adb("Xiaomi 13T", "Mozilla/5.0 (Linux; Android 13; 2306EPN60G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (ARM)", _ANR("Mali-G715"), 8, 8),
    _adb("Xiaomi 12T Pro", "Mozilla/5.0 (Linux; Android 13; 22081212UG Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 8),
    _adb("Xiaomi 11", "Mozilla/5.0 (Linux; Android 12; M2102J20SG Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 780, 717, 2.75, "Google Inc. (Qualcomm)", _ANQ("660"), 8, 8),
    _adb("Xiaomi Redmi Note 13 Pro", "Mozilla/5.0 (Linux; Android 13; 23090RA98G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 782, 2.75, "Google Inc. (ARM)", _ANR("Mali-G610"), 8, 8),
    _adb("Xiaomi Redmi Note 14 Pro", "Mozilla/5.0 (Linux; Android 14; 24094RAD4I Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G720"), 8, 8),
    _adb("Xiaomi Redmi Note 12 Pro", "Mozilla/5.0 (Linux; Android 13; 22101320G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G68"), 8, 8),
    _adb("Xiaomi Redmi Note 12", "Mozilla/5.0 (Linux; Android 13; 23021RAAEG Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 4, 6),
    _adb("Xiaomi Redmi 13C", "Mozilla/5.0 (Linux; Android 13; 23107RAH2G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Xiaomi Redmi 12", "Mozilla/5.0 (Linux; Android 13; 23053RN02G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Xiaomi Redmi 10", "Mozilla/5.0 (Linux; Android 12; 21061119AG Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 800, 730, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Xiaomi POCO X6 Pro", "Mozilla/5.0 (Linux; Android 14; 2311DRK48G Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 839, 2.625, "Google Inc. (ARM)", _ANR("Mali-G615 MC6"), 8, 8),
    _adb("Xiaomi POCO F6", "Mozilla/5.0 (Linux; Android 14; 24069PC21G Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Xiaomi POCO M6 Pro", "Mozilla/5.0 (Linux; Android 14; 24040PC25G Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57 MC2"), 4, 4),
    # ── OnePlus ─────────────────────────────────────────────────────────────────
    _adb("OnePlus 13", "Mozilla/5.0 (Linux; Android 15; CPH2653 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("830"), 8, 12),
    _adb("OnePlus 12", "Mozilla/5.0 (Linux; Android 14; PJD110 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 16),
    _adb("OnePlus 12R", "Mozilla/5.0 (Linux; Android 14; CPH2609 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("OnePlus 11", "Mozilla/5.0 (Linux; Android 14; CPH2449 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 12),
    _adb("OnePlus Nord 4", "Mozilla/5.0 (Linux; Android 14; CPH2663 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("732"), 8, 12),
    _adb("OnePlus Nord CE 4", "Mozilla/5.0 (Linux; Android 14; CPH2613 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 8),
    _adb("OnePlus 10 Pro", "Mozilla/5.0 (Linux; Android 13; NE2213 Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 12),
    _adb("OnePlus Ace 3", "Mozilla/5.0 (Linux; Android 14; PJA110 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    # ── vivo / iQOO ─────────────────────────────────────────────────────────────
    _adb("vivo V2334", "Mozilla/5.0 (Linux; Android 16; V2334 Build/BP2A.250605.031) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 360, 800, 740, 2.75, "Google Inc. (ARM)", _ANR("Mali-G610 MC6"), 8, 8),
    _adb("vivo X200 Pro", "Mozilla/5.0 (Linux; Android 15; V2413 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (ARM)", _ANR("Mali-G925"), 12, 16),
    _adb("vivo X200", "Mozilla/5.0 (Linux; Android 15; V2339 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (ARM)", _ANR("Immortalis-G925"), 8, 12),
    _adb("vivo V40", "Mozilla/5.0 (Linux; Android 14; V2347 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 12),
    _adb("vivo V30", "Mozilla/5.0 (Linux; Android 14; V2318 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (Qualcomm)", _ANQ("732"), 8, 8),
    _adb("vivo Y36", "Mozilla/5.0 (Linux; Android 13; V2312 Build/TQ3A.230805.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
    _adb("iQOO 12", "Mozilla/5.0 (Linux; Android 14; V2307A Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("iQOO Neo 9 Pro", "Mozilla/5.0 (Linux; Android 14; V2338A Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    # ── OPPO ────────────────────────────────────────────────────────────────────
    _adb("Oppo Find X8", "Mozilla/5.0 (Linux; Android 15; CPH2651 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 780, 3, "Google Inc. (ARM)", _ANR("Mali-G925"), 8, 16),
    _adb("Oppo Find X8 Pro", "Mozilla/5.0 (Linux; Android 15; CPH2667 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (ARM)", _ANR("Mali-G925"), 12, 16),
    _adb("Oppo Find X7", "Mozilla/5.0 (Linux; Android 14; PHZ110 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (ARM)", _ANR("Mali-G720"), 8, 12),
    _adb("Oppo Reno 13", "Mozilla/5.0 (Linux; Android 15; CPH2681 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (ARM)", _ANR("Mali-G720"), 8, 12),
    _adb("Oppo Reno 12", "Mozilla/5.0 (Linux; Android 14; CPH2625 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (ARM)", _ANR("Mali-G610"), 8, 8),
    _adb("Oppo Reno 11", "Mozilla/5.0 (Linux; Android 13; CPH2599 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G610"), 8, 8),
    _adb("Oppo A60", "Mozilla/5.0 (Linux; Android 14; CPH2665 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 4, 4),
    # ── Honor ───────────────────────────────────────────────────────────────────
    _adb("Honor Magic V3", "Mozilla/5.0 (Linux; Android 14; FCP-AN10 Build/HONORFCP-AN10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 780, 724, 2.5, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 16),
    _adb("Honor Magic 7 Pro", "Mozilla/5.0 (Linux; Android 15; PGT-AN20 Build/HONORPGT-AN20) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("830"), 12, 16),
    _adb("Honor Magic 6 Pro", "Mozilla/5.0 (Linux; Android 14; BVL-AN00 Build/HONORBVL-AN00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3.5, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 12),
    _adb("Honor 200", "Mozilla/5.0 (Linux; Android 14; ELI-AN00 Build/HONORELI-AN00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 8),
    _adb("Honor X9b", "Mozilla/5.0 (Linux; Android 13; ALI-NX1 Build/HONORALI-NX1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 8, 8),
    _adb("Honor X7", "Mozilla/5.0 (Linux; Android 13; JLN-LX1 Build/HONORJLN-LX1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 360, 780, 717, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 4, 4),
    _adb("Honor 90", "Mozilla/5.0 (Linux; Android 13; REA-AN00 Build/HONORREA-AN00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("644"), 8, 8),
    # ── Motorola ────────────────────────────────────────────────────────────────
    _adb("Motorola Moto G85", "Mozilla/5.0 (Linux; Android 14; Moto G85 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("619"), 8, 8),
    _adb("Motorola Edge 50 Pro", "Mozilla/5.0 (Linux; Android 14; XT2403-1 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 2.75, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 12),
    _adb("Motorola Edge 50", "Mozilla/5.0 (Linux; Android 14; XT2407-1 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 8),
    _adb("Motorola Edge 50 Ultra", "Mozilla/5.0 (Linux; Android 14; XT2401-2 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Motorola Moto G84", "Mozilla/5.0 (Linux; Android 13; XT2347-1 Build/T1TD33.61-24-1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("619"), 8, 8),
    _adb("Motorola Moto G54", "Mozilla/5.0 (Linux; Android 13; XT2343-2 Build/T1TD33.61-24-1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
    _adb("Motorola Moto G24", "Mozilla/5.0 (Linux; Android 14; XT2423-5 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Motorola Razr 50 Ultra", "Mozilla/5.0 (Linux; Android 14; XT2451-3 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 892, 830, 3.5, "Google Inc. (Qualcomm)", _ANQ("735"), 8, 12),
    _adb("Motorola Razr 40 Ultra", "Mozilla/5.0 (Linux; Android 13; XT2321-2 Build/T1TD33.61-24-1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 412, 892, 830, 3.5, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 8),
    # ── Realme ──────────────────────────────────────────────────────────────────
    _adb("Realme GT 7 Pro", "Mozilla/5.0 (Linux; Android 15; RMX5090 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("830"), 12, 16),
    _adb("Realme GT 6", "Mozilla/5.0 (Linux; Android 14; RMX3802 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("735"), 8, 12),
    _adb("Realme GT 5", "Mozilla/5.0 (Linux; Android 13; RMX3820 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("740"), 8, 12),
    _adb("Realme 12 Pro", "Mozilla/5.0 (Linux; Android 14; RMX3842 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("644"), 8, 8),
    _adb("Realme C67", "Mozilla/5.0 (Linux; Android 13; RMX3760 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 4, 4),
    _adb("Realme C65", "Mozilla/5.0 (Linux; Android 14; RMX3900 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
    # ── Nothing / CMF ───────────────────────────────────────────────────────────
    _adb("Nothing Phone (3)", "Mozilla/5.0 (Linux; Android 15; A059 Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 783, 2, "Google Inc. (Qualcomm)", _ANQ("735"), 8, 12),
    _adb("Nothing Phone (2)", "Mozilla/5.0 (Linux; Android 14; A065 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 12),
    _adb("Nothing Phone (2a)", "Mozilla/5.0 (Linux; Android 14; A142 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 852, 782, 2.75, "Google Inc. (ARM)", _ANR("Mali-G615"), 8, 8),
    _adb("CMF Phone 1", "Mozilla/5.0 (Linux; Android 14; A015 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G615"), 8, 8),
    # ── Asus ROG / Zenfone ──────────────────────────────────────────────────────
    _adb("Asus ROG Phone 9", "Mozilla/5.0 (Linux; Android 15; ASUS_AI2401_C Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 12, 16),
    _adb("Asus ROG Phone 8", "Mozilla/5.0 (Linux; Android 14; ASUS_AI2401_A Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Asus Zenfone 11 Ultra", "Mozilla/5.0 (Linux; Android 14; ASUS_AI2401_H Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 915, 829, 3, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    # ── Sony Xperia ─────────────────────────────────────────────────────────────
    _adb("Sony Xperia 1 VI", "Mozilla/5.0 (Linux; Android 14; XQ-DQ72 Build/67.1.A.2.97) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 411, 891, 830, 2.625, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 12),
    _adb("Sony Xperia 5 VI", "Mozilla/5.0 (Linux; Android 14; XQ-ES72 Build/67.1.A.2.97) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 411, 891, 830, 2.625, "Google Inc. (Qualcomm)", _ANQ("750"), 8, 8),
    # ── Infinix / Tecno / Nokia / HTC / TCL / ZTE (emerging-market volume) ──────
    _adb("Infinix Note 40", "Mozilla/5.0 (Linux; Android 14; X6862B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G615"), 8, 8),
    _adb("Infinix Hot 40i", "Mozilla/5.0 (Linux; Android 13; X6527B Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G52"), 4, 4),
    _adb("Tecno Camon 30", "Mozilla/5.0 (Linux; Android 14; CK9N Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G610"), 8, 8),
    _adb("Tecno Spark 20", "Mozilla/5.0 (Linux; Android 13; CK7N Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
    _adb("Nokia G42", "Mozilla/5.0 (Linux; Android 13; TA-1589 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (Qualcomm)", _ANQ("610"), 4, 4),
    _adb("Nokia X30", "Mozilla/5.0 (Linux; Android 13; TA-1550 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36", 412, 892, 830, 2.625, "Google Inc. (Qualcomm)", _ANQ("730"), 8, 8),
    _adb("HTC U24 Pro", "Mozilla/5.0 (Linux; Android 14; 2QJ1P Build/UKQ1.230917.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36", 393, 852, 782, 3, "Google Inc. (Qualcomm)", _ANQ("720"), 8, 8),
    _adb("TCL 50 SE", "Mozilla/5.0 (Linux; Android 14; T612K Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
    _adb("ZTE Blade V50", "Mozilla/5.0 (Linux; Android 13; Blade V50 Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36", 393, 851, 781, 2.75, "Google Inc. (ARM)", _ANR("Mali-G57"), 4, 4),
]

# ─── Locale / geo fallbacks ───────────────────────────────────────────────────

LOCALE_PROFILES = [
    {"lang": "en-US", "timezone": "America/New_York", "geo": "US"},
    {"lang": "en-US", "timezone": "America/Chicago", "geo": "US"},
    {"lang": "en-US", "timezone": "America/Los_Angeles", "geo": "US"},
    {"lang": "en-GB", "timezone": "Europe/London", "geo": "GB"},
    {"lang": "de-DE", "timezone": "Europe/Berlin", "geo": "DE"},
    {"lang": "fr-FR", "timezone": "Europe/Paris", "geo": "FR"},
    {"lang": "es-ES", "timezone": "Europe/Madrid", "geo": "ES"},
    {"lang": "pt-BR", "timezone": "America/Sao_Paulo", "geo": "BR"},
    {"lang": "hi-IN", "timezone": "Asia/Kolkata", "geo": "IN"},
    {"lang": "ja-JP", "timezone": "Asia/Tokyo", "geo": "JP"},
    {"lang": "ko-KR", "timezone": "Asia/Seoul", "geo": "KR"},
    {"lang": "zh-CN", "timezone": "Asia/Shanghai", "geo": "CN"},
    {"lang": "ru-RU", "timezone": "Europe/Moscow", "geo": "RU"},
    {"lang": "ar-SA", "timezone": "Asia/Riyadh", "geo": "SA"},
    {"lang": "nl-NL", "timezone": "Europe/Amsterdam", "geo": "NL"},
    {"lang": "it-IT", "timezone": "Europe/Rome", "geo": "IT"},
    {"lang": "pl-PL", "timezone": "Europe/Warsaw", "geo": "PL"},
    {"lang": "tr-TR", "timezone": "Europe/Istanbul", "geo": "TR"},
    {"lang": "id-ID", "timezone": "Asia/Jakarta", "geo": "ID"},
    {"lang": "th-TH", "timezone": "Asia/Bangkok", "geo": "TH"},
]

# Country → browser language used when the proxy IP decides the location.
COUNTRY_LANGS = {
    "US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA", "IN": "hi-IN",
    "DE": "de-DE", "AT": "de-AT", "CH": "de-CH", "FR": "fr-FR", "BE": "fr-BE",
    "NL": "nl-NL", "ES": "es-ES", "MX": "es-MX", "AR": "es-AR", "CO": "es-CO",
    "PT": "pt-PT", "BR": "pt-BR", "IT": "it-IT", "JP": "ja-JP", "KR": "ko-KR",
    "CN": "zh-CN", "TW": "zh-TW", "HK": "zh-HK", "RU": "ru-RU", "UA": "uk-UA",
    "SA": "ar-SA", "AE": "ar-AE", "EG": "ar-EG", "TR": "tr-TR", "PL": "pl-PL",
    "ID": "id-ID", "TH": "th-TH", "VN": "vi-VN", "PH": "en-PH", "MY": "ms-MY",
    "SE": "sv-SE", "NO": "no-NO", "DK": "da-DK", "FI": "fi-FI", "CZ": "cs-CZ",
    "RO": "ro-RO", "HU": "hu-HU", "GR": "el-GR", "IL": "he-IL", "ZA": "en-ZA",
    "NG": "en-NG", "PK": "ur-PK", "BD": "bn-BD", "KE": "en-KE",
}

YOUTUBE_REFERRERS = [
    "https://www.youtube.com/watch?v=8A2LHzyevJA",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/",
    "https://m.youtube.com/",
    "https://www.youtube.com/shorts/",
    "https://www.youtube.com/results?search_query=video",
]

CANVAS_NOISE_SEEDS = [0.02, -0.03, 0.01, -0.02, 0.04, -0.01, 0.03, -0.04, 0.015, -0.025]
AUDIO_OFFSETS = [0.0001, -0.0002, 0.0003, -0.0001, 0.0002, -0.0003, 0.00015, -0.00025]

def _pick(arr):
    return random.choice(arr)


def _country_lang(country):
    return COUNTRY_LANGS.get(country, "en-US")


def generate_profile(device_kind=None, youtube=False, geo=None):
    """Build a coherent Android device profile.

    device_kind: ignored — the fleet is 100% Android (desktop cut out). Kept for
    backward-call compatibility; always picks a random phone.
    geo: optional dict from an IP geolocation lookup —
         {"country": "IN", "timezone": "Asia/Kolkata", "lat": .., "lon": ..}
         When given, timezone/locale/geolocation match the real proxy IP.
    """
    dev = _pick(ANDROID_DEVICES)

    if geo and geo.get("country"):
        country = geo.get("country", "")
        lang = _country_lang(country)
        timezone = geo.get("timezone") or _pick(LOCALE_PROFILES)["timezone"]
        geo_code = country
    else:
        locale = _pick(LOCALE_PROFILES)
        lang = locale["lang"]
        timezone = locale["timezone"]
        geo_code = locale["geo"]

    base_lang = lang.split("-")[0]
    languages = [lang, base_lang]
    if "en" not in [l.split("-")[0] for l in languages]:
        languages.append("en")

    profile = {
        "name": dev["name"],
        "deviceKind": "mobile",
        "userAgent": dev["ua"],
        "viewport": dict(dev["viewport"]),
        "screen": dict(dev["screen"]),
        "deviceScaleFactor": dev["dpr"],
        "touch": dev["touch"],
        "maxTouchPoints": dev["maxTouchPoints"],
        "platform": dev["platform"],
        "webgl": dev["webgl"],
        "hardwareConcurrency": dev["hw"],
        "deviceMemory": dev["mem"],
        "locale": lang,
        "timezone": timezone,
        "geo": geo_code,
        "languages": languages,
        "canvasNoiseSeed": _pick(CANVAS_NOISE_SEEDS),
        "audioOffset": _pick(AUDIO_OFFSETS),
        "colorDepth": _pick([24, 30, 32]),
        "geoLat": (geo or {}).get("lat") if geo else None,
        "geoLon": (geo or {}).get("lon") if geo else None,
    }
    if youtube:
        profile["youtubeReferer"] = _pick(YOUTUBE_REFERRERS)
    return profile


if __name__ == "__main__":
    youtube = "youtube=true" in sys.argv or "youtube=1" in sys.argv
    prof = generate_profile(youtube=youtube)
    print(json.dumps(prof))
