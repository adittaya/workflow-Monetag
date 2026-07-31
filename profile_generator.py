import random
import json
import sys

MOBILE_UAS = [
    'Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro Build/BP1A.250305.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 15; Samsung Galaxy S25 Ultra SM-S938B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 15; Xiaomi 15 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; OnePlus 13 5G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 15; vivo X200 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; Oppo Find X8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 15; Nothing Phone 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.186 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; Google Pixel 8a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.186 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 15; OnePlus 12 5G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.186 Mobile Safari/537.36',
]

DESKTOP_UAS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.2651.98',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0',
]

MOBILE_VIEWPORTS = [
    {"width": 360, "height": 780},
    {"width": 375, "height": 812},
    {"width": 390, "height": 844},
    {"width": 412, "height": 915},
    {"width": 414, "height": 896},
    {"width": 393, "height": 852},
    {"width": 430, "height": 932},
    {"width": 384, "height": 854},
    {"width": 412, "height": 914},
    {"width": 360, "height": 760},
]

DESKTOP_VIEWPORTS = [
    {"width": 1280, "height": 720},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
]

YOUTUBE_REFERRERS = [
    "https://www.youtube.com/watch?v=8A2LHzyevJA",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/",
    "https://m.youtube.com/",
    "https://www.youtube.com/shorts/",
    "https://www.youtube.com/results?search_query=video",
]

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

WEBGL_PROFILES = [
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Apple)", "renderer": "Apple GPU"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.6)"},
]

CANVAS_NOISE_SEEDS = [0.02, -0.03, 0.01, -0.02, 0.04, -0.01, 0.03, -0.04, 0.015, -0.025]
AUDIO_OFFSETS = [0.0001, -0.0002, 0.0003, -0.0001, 0.0002, -0.0003, 0.00015, -0.00025]

DEVICE_SCALE_FACTORS = [1, 1.5, 2, 2.5, 3, 3.5]


def _pick(arr):
    return random.choice(arr)


def generate_profile(mobile=True, youtube=False):
    ua = _pick(MOBILE_UAS) if mobile else _pick(DESKTOP_UAS)
    viewport = _pick(MOBILE_VIEWPORTS) if mobile else _pick(DESKTOP_VIEWPORTS)
    locale = _pick(LOCALE_PROFILES)
    webgl = _pick(WEBGL_PROFILES)
    hw_concurrency = _pick([2, 4, 6, 8, 12, 16])
    device_memory = _pick([2, 4, 8, 16])
    dpr = _pick(DEVICE_SCALE_FACTORS) if mobile else 1.0

    profile = {
        "userAgent": ua,
        "viewport": viewport,
        "locale": locale["lang"],
        "timezone": locale["timezone"],
        "geo": locale["geo"],
        "languages": [locale["lang"].split("-")[0], "en"],
        "webgl": webgl,
        "hardwareConcurrency": hw_concurrency,
        "deviceMemory": device_memory,
        "canvasNoiseSeed": _pick(CANVAS_NOISE_SEEDS),
        "audioOffset": _pick(AUDIO_OFFSETS),
        "deviceScaleFactor": dpr,
        "screen": {
            "width": viewport["width"] + random.randint(0, 360),
            "height": viewport["height"] + random.randint(200, 500),
            "availWidth": viewport["width"],
            "availHeight": viewport["height"] - random.randint(40, 80),
            "colorDepth": _pick([24, 30, 32]),
        },
        "platform": "Linux armv81" if mobile else (
            "MacIntel" if "Mac" in ua else ("Linux x86_64" if "Linux" in ua else "Win32")
        ),
    }
    if youtube:
        profile["youtubeReferer"] = _pick(YOUTUBE_REFERRERS)
    return profile


if __name__ == "__main__":
    mobile = "mobile=true" in sys.argv or "mobile=1" in sys.argv
    youtube = "youtube=true" in sys.argv or "youtube=1" in sys.argv
    prof = generate_profile(mobile=mobile, youtube=youtube)
    print(json.dumps(prof))
