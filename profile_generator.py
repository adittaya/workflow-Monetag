import random
import json
import sys

# ─── Android devices — coherent UA ↔ viewport ↔ dpr ↔ GPU ↔ platform ─────────
# Each device is a complete, internally-consistent fingerprint bundle. Picking a
# device picks ALL of its attributes together so nothing diverges (a mobile UA
# never pairs with a desktop GPU string, wrong viewport, or wrong touch config).

ANDROID_DEVICES = [
    {
        "name": "Google Pixel 9 Pro",
        "ua": "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro Build/AP4A.250505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915, "availWidth": 412, "availHeight": 839},
        "dpr": 2.625, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G715, OpenGL ES 3.2 ANGLE (ARM, Mali-G715, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Google Pixel 8a",
        "ua": "Mozilla/5.0 (Linux; Android 15; Pixel 8a Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.8054.36 Mobile Safari/537.36",
        "viewport": {"width": 360, "height": 780},
        "screen": {"width": 360, "height": 780, "availWidth": 360, "availHeight": 717},
        "dpr": 2.625, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G715, OpenGL ES 3.2 ANGLE (ARM, Mali-G715, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Samsung Galaxy S25 Ultra",
        "ua": "Mozilla/5.0 (Linux; Android 15; SM-S938B Build/BPF6.250505.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915, "availWidth": 412, "availHeight": 829},
        "dpr": 3.5, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2))"},
        "hw": 8, "mem": 12,
    },
    {
        "name": "Samsung Galaxy A55",
        "ua": "Mozilla/5.0 (Linux; Android 14; SM-A556B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36",
        "viewport": {"width": 360, "height": 780},
        "screen": {"width": 360, "height": 780, "availWidth": 360, "availHeight": 709},
        "dpr": 2.75, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G68, OpenGL ES 3.2 ANGLE (ARM, Mali-G68, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Xiaomi 15 Pro",
        "ua": "Mozilla/5.0 (Linux; Android 15; 25032RP21G Build/AQ3A.250515.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 393, "height": 852},
        "screen": {"width": 393, "height": 852, "availWidth": 393, "availHeight": 782},
        "dpr": 3, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2))"},
        "hw": 8, "mem": 12,
    },
    {
        "name": "Xiaomi Redmi Note 13 Pro",
        "ua": "Mozilla/5.0 (Linux; Android 13; 23090RA98G Build/TKQ1.221114.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36",
        "viewport": {"width": 393, "height": 851},
        "screen": {"width": 393, "height": 851, "availWidth": 393, "availHeight": 782},
        "dpr": 2.75, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G610, OpenGL ES 3.2 ANGLE (ARM, Mali-G610, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "OnePlus 13",
        "ua": "Mozilla/5.0 (Linux; Android 15; CPH2653 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915, "availWidth": 412, "availHeight": 829},
        "dpr": 3.5, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 830, OpenGL ES 3.2))"},
        "hw": 8, "mem": 12,
    },
    {
        "name": "vivo V2334",
        "ua": "Mozilla/5.0 (Linux; Android 16; V2334 Build/BP2A.250605.031) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 360, "height": 800},
        "screen": {"width": 360, "height": 800, "availWidth": 360, "availHeight": 740},
        "dpr": 2.75, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G610 MC6, OpenGL ES 3.2 ANGLE (ARM, Mali-G610 MC6, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Nothing Phone (3)",
        "ua": "Mozilla/5.0 (Linux; Android 15; A059 Build/AP2A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36",
        "viewport": {"width": 393, "height": 852},
        "screen": {"width": 393, "height": 852, "availWidth": 393, "availHeight": 783},
        "dpr": 2, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 735, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 735, OpenGL ES 3.2))"},
        "hw": 8, "mem": 12,
    },
    {
        "name": "Oppo Find X8",
        "ua": "Mozilla/5.0 (Linux; Android 15; CPH2651 Build/AP1A.240505.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.47 Mobile Safari/537.36",
        "viewport": {"width": 393, "height": 852},
        "screen": {"width": 393, "height": 852, "availWidth": 393, "availHeight": 780},
        "dpr": 3, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (ARM)", "renderer": "ANGLE (ARM, Mali-G925, OpenGL ES 3.2 ANGLE (ARM, Mali-G925, OpenGL ES 3.2))"},
        "hw": 8, "mem": 16,
    },
    {
        "name": "Motorola Moto G85",
        "ua": "Mozilla/5.0 (Linux; Android 14; Moto G85 Build/U1RD1.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.7851.40 Mobile Safari/537.36",
        "viewport": {"width": 393, "height": 851},
        "screen": {"width": 393, "height": 851, "availWidth": 393, "availHeight": 781},
        "dpr": 2.75, "touch": True, "maxTouchPoints": 5,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 619, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 619, OpenGL ES 3.2))"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Honor Magic V3",
        "ua": "Mozilla/5.0 (Linux; Android 14; FCP-AN10 Build/HONORFCP-AN10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7730.38 Mobile Safari/537.36",
        "viewport": {"width": 360, "height": 780},
        "screen": {"width": 360, "height": 780, "availWidth": 360, "availHeight": 724},
        "dpr": 2.5, "touch": True, "maxTouchPoints": 10,
        "platform": "Linux armv8l",
        "webgl": {"vendor": "Google Inc. (Qualcomm)", "renderer": "ANGLE (Qualcomm, Adreno (TM) 750, OpenGL ES 3.2 ANGLE (Qualcomm, Adreno (TM) 750, OpenGL ES 3.2))"},
        "hw": 8, "mem": 16,
    },
]

# ─── Desktop combos — coherent OS ↔ UA ↔ screen ↔ GPU ─────────────────────────

DESKTOP_COMBOS = [
    {
        "name": "Windows 11 / Chrome",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "viewport": {"width": 1280, "height": 720},
        "screen": {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1040},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Win32",
        "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        "hw": 8, "mem": 16,
    },
    {
        "name": "Windows 11 / Edge",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.2641.42",
        "viewport": {"width": 1536, "height": 864},
        "screen": {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1040},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Win32",
        "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        "hw": 12, "mem": 16,
    },
    {
        "name": "Windows 10 / Chrome",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "screen": {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1040},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Win32",
        "webgl": {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "macOS Sequoia / Chrome",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "screen": {"width": 2560, "height": 1440, "availWidth": 2560, "availHeight": 1400},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "MacIntel",
        "webgl": {"vendor": "Google Inc. (Apple)", "renderer": "Apple GPU"},
        "hw": 10, "mem": 16,
    },
    {
        "name": "macOS Ventura / Chrome",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "viewport": {"width": 1512, "height": 982},
        "screen": {"width": 2560, "height": 1440, "availWidth": 2560, "availHeight": 1400},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "MacIntel",
        "webgl": {"vendor": "Google Inc. (Apple)", "renderer": "Apple GPU"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Ubuntu / Chrome",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "viewport": {"width": 1536, "height": 864},
        "screen": {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1050},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Linux x86_64",
        "webgl": {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.5)"},
        "hw": 8, "mem": 8,
    },
    {
        "name": "Debian / Chrome",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 2560, "height": 1440, "availWidth": 2560, "availHeight": 1400},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Linux x86_64",
        "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, Mesa NVIDIA GeForce GTX 1060 6GB, OpenGL 4.5)"},
        "hw": 12, "mem": 16,
    },
    {
        "name": "Windows 11 / Chrome (Iris Xe)",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 2560, "height": 1440, "availWidth": 2560, "availHeight": 1400},
        "dpr": 1, "touch": False, "maxTouchPoints": 0,
        "platform": "Win32",
        "webgl": {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        "hw": 12, "mem": 16,
    },
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

DESKTOP_WEIGHT = 0.4  # 40% desktop / 60% Android


def _pick(arr):
    return random.choice(arr)


def _country_lang(country):
    return COUNTRY_LANGS.get(country, "en-US")


def generate_profile(device_kind=None, youtube=False, geo=None):
    """Build a coherent device profile.

    device_kind: "desktop" | "mobile" | None (None → 40% desktop / 60% Android)
    geo: optional dict from an IP geolocation lookup —
         {"country": "IN", "timezone": "Asia/Kolkata", "lat": .., "lon": ..}
         When given, timezone/locale/geolocation match the real proxy IP.
    """
    if device_kind is None:
        device_kind = "desktop" if random.random() < DESKTOP_WEIGHT else "mobile"

    if device_kind == "desktop":
        dev = _pick(DESKTOP_COMBOS)
    else:
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
        "deviceKind": device_kind,
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
    kind = None
    if "desktop=true" in sys.argv or "desktop=1" in sys.argv:
        kind = "desktop"
    elif "mobile=true" in sys.argv or "mobile=1" in sys.argv:
        kind = "mobile"
    youtube = "youtube=true" in sys.argv or "youtube=1" in sys.argv
    prof = generate_profile(device_kind=kind, youtube=youtube)
    print(json.dumps(prof))
