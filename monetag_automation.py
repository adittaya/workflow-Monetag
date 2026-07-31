#!/usr/bin/env python3
"""Monetag SmartLink automation engine — SmartLink search + view verification.

Follows a Monetag SmartLink through its full redirect chain (HTTP 3xx, meta
refresh, JS window.location) to the final rotating offer landing page, then
verifies that a GENUINE view occurred using a multi-signal scoring system.

Reuses the proven project infrastructure: proxy pool rotation (Supabase),
randomized behavioral profiles + stealth JS, PageMonitor (MutationObserver +
network interceptors), adaptive timeouts, human-like interaction, Cloudflare /
challenge / CSS-shell detection and raw-HTML redirect extraction.

Usage:
    python3 monetag_automation.py <smartlink_url> [--views N] [--verify-mode strict|lenient]
        [--traffic-source youtube|google|facebook|twitter|direct] [--debug]

Env vars (CI / headless):
    MONETAG_SMARTLINK_URL   SmartLink URL to visit (required if no argv)
    MONETAG_DEVICE         desktop|mobile|auto (default: auto → 40% desktop / 60% Android)
    MONETAG_PROXY           http://ip:port proxy for this session (IP geolocation drives locale/timezone)
    MONETAG_TRAFFIC_SOURCE  referrer/UTM profile (default: youtube)
    MONETAG_VERIFY_MODE     strict|lenient (default: strict)
    MONETAG_VIEWS           number of view cycles to run (default: 1)
    MONETAG_REFERER         exact referrer URL to inject (overrides traffic source)
    MONETAG_HEADLESS        "1" to force headless
    MONETAG_DEBUG           "1" to save screenshots
    MONETAG_HARD_TIMEOUT    per-cycle seconds cap (default: 60)
    ADSPOWER_PROFILE_ID     when set, drive ONE fixed AdsPower profile via its
                            Local API (default http://127.0.0.1:50325, override
                            with ADSPOWER_API_BASE). MONETAG_PROXY is bound to
                            the profile per view via launch args; the profile's
                            own device fingerprint is used (no local emulation).

Output:
    view_report.json  — per-cycle view records + aggregate summary
    stdout            — human summary with verdicts
    exit 0  all views VERIFIED/LIKELY
    exit 2  all views blocked/invalid (proxy-level failure)
    exit 3  mixed / no views produced
"""

import json
import os
import random
import re
import signal
import sys
import threading
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

try:
    from proxy_rotator import mark_dead, mark_proxy_used, get_proxy
except ImportError:
    mark_dead = lambda *a, **kw: False
    mark_proxy_used = lambda *a, **kw: False
    get_proxy = None

from profile_generator import generate_profile

# ── Globals ──
SMARTLINK_URL = ""
VIEWS_TOTAL = 1
VERIFY_MODE = "strict"
DEBUG = False
driver = None
profile = None
start_time = time.time()
monitor = None

PROXY = os.environ.get("MONETAG_PROXY", "")
PROXY_HOST = PROXY.replace("https://", "").replace("http://", "").split(":")[0] if PROXY else ""
PROXY_IP = PROXY_HOST
PROXY_PORT = int(PROXY.split(":")[-1]) if PROXY and ":" in PROXY.split("//")[-1] else 0

# ── AdsPower mode ──
# When ADSPOWER_PROFILE_ID is set, the engine drives the SAME fixed AdsPower
# profile every view (one stable device fingerprint), binding the current
# MONETAG_PROXY to it via AdsPower launch args. AdsPower runs locally on the
# same host (CI runner / VPS) and exposes its Local API on ADSPOWER_API_BASE.
ADSPOWER_PROFILE_ID = os.environ.get("ADSPOWER_PROFILE_ID", "").strip()
ADSPOWER_API_BASE = os.environ.get("ADSPOWER_API_BASE", "http://127.0.0.1:50325")
ADS_POWER = bool(ADSPOWER_PROFILE_ID)

proxy_failures = 0
proxy_blocked = False
proxy_punished = False
MAX_PROXY_RESTARTS = 3

TRAFFIC_SOURCE = os.environ.get("MONETAG_TRAFFIC_SOURCE", "youtube").lower()
TRAFFIC_REFERRERS = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "facebook": "https://www.facebook.com/",
    "twitter": "https://x.com/",
    "direct": "",
}
TRAFFIC_UTM = {
    "youtube": {"utm_source": "youtube", "utm_medium": "referral", "utm_campaign": "smartlink"},
    "google": {"utm_source": "google", "utm_medium": "organic", "utm_campaign": "search"},
    "facebook": {"utm_source": "facebook", "utm_medium": "social", "utm_campaign": "post"},
    "twitter": {"utm_source": "twitter", "utm_medium": "social", "utm_campaign": "tweet"},
    "direct": {},
}

# ── Monetag / ad-network domains that should NOT be the final view target ──
AD_NETWORK_DOMAINS = [
    "oclasrv.com", "go.oclasrv.com",
    "monetag.com", "www.monetag.com", "smart.monetag.com", "omg10.com",
    "propellerads.com", "propelleradsmedia.com",
    "adskeeper.com", "adsterra.com", "hilltopads.com",
    "googleadservices.com", "googlesyndication.com", "doubleclick.net",
    "adnxs.com", "taboola.com", "outbrain.com", "mgid.com",
    "exoclick.com", "trafficjunky.com", "popads.net", "clickadu.com",
]
SMARTLINK_DOMAINS = [
    "oclasrv.com", "go.oclasrv.com", "monetag.com", "smart.monetag.com", "omg10.com",
]

OFFER_SIGNAL_DOMAINS = [
    "play.google.com", "apps.apple.com", "app.adjust.com",
    "t.me", "telegram.me", "wa.me", "api.whatsapp.com",
    "aff", "click", "track", "redirect", "gateway",
]

BLOCK_SIGNATURES = [
    "cf-browser-verification", "challenge-form", "cf-challenge",
    "_cf_chl_opt", "challenges.cloudflare.com", "turnstile", "__cf_chl_tk",
    "checking your browser", "verify you are human", "cf-chl",
    "attention required", "access denied", "forbidden", "404 not found",
    "page not found", "captcha", "puzzle", "something went wrong",
    "sorry, you have been blocked", "website unavailable",
]

# ── View verification weights ──
VIEW_WEIGHTS = {
    "left_network": 20,      # redirect chain left the smartlink/ad network
    "page_rendered": 20,     # real page rendered (readyState, content, DOM)
    "js_healthy": 10,        # JavaScript executing on the landing page
    "not_blocked": 15,       # no CAPTCHA / challenge / 403 / empty shell
    "offer_signals": 15,     # app store / telegram / CTAs / real content
    "network_evidence": 10,  # network requests fired (pixels, images)
    "dwell_time": 10,        # stayed on landing human-like duration
}


def _check_native_binary(path: str) -> bool:
    """Check if path is a runnable binary (ELF binary or shebang script)."""
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            return header in (b"\x7fELF", b"#!/u", b"#!/b", b"#!/s")
    except OSError:
        return False


def _detect_chrome_binary() -> str:
    """Find a working Chrome/Chromium binary. Always returns a string."""
    import shutil
    candidates = [
        "/opt/google/chrome/chrome",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    env_path = os.environ.get("CHROMIUM_PATH", "")
    if env_path:
        candidates.insert(0, env_path)
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium", "google-chrome-beta"):
        which = shutil.which(name)
        if which:
            candidates.insert(0, which)
    for p in candidates:
        if _check_native_binary(p):
            return p
    for p in candidates:
        if os.path.exists(p):
            return p
    return "/usr/bin/chromium-browser"


# ── Logging / timing ──
def log(msg):
    print(f"  [{time.time() - start_time:.1f}s] {msg}", file=sys.stderr)


def ms(t):
    time.sleep(t / 1000.0)


def rand(min_val, max_val):
    return random.randint(min_val, max_val)


def safe_url():
    try:
        return driver.current_url
    except Exception:
        return ""


def url_base(u):
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
        return p.scheme + "://" + p.netloc + p.path
    except Exception:
        return (u or "").split("#")[0]


def safe_eval(script, *args):
    try:
        return driver.execute_script(script, *args)
    except Exception:
        return None


def get_page_height():
    h = safe_eval("return document.documentElement.scrollHeight;")
    return int(h) if h is not None else 0


def get_body_text_length():
    l = safe_eval("return (document.body ? document.body.textContent : '').length;")
    return int(l) if l is not None else 0


def wait_for_page_ready(min_height=200, timeout_sec=20):
    """Wait for page to be fully loaded with actual content rendered.
    Returns (ready, page_height, body_text_len)."""
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        state = safe_eval("return document.readyState;") or ""
        height = get_page_height()
        body_len = get_body_text_length()
        if state == "complete" and height >= min_height and body_len > 100:
            return True, height, body_len
        if state == "complete" and body_len > 200:
            return True, height, body_len
        ms(500)
    height = get_page_height()
    body_len = get_body_text_length()
    return False, height, body_len


def verify_js_working():
    """Check if JavaScript is actually executing on the page."""
    return safe_eval("""
        try {
            var t = document.createTextNode('');
            document.body.appendChild(t);
            t.remove();
            return true;
        } catch(e) {
            return false;
        }
    """) or False


def get_raw_html(max_len=5000):
    """Get raw HTML source from the page. Works even when JS doesn't execute."""
    return safe_eval(f"return (document.documentElement.outerHTML || '').substring(0, {max_len});") or ""


def extract_redirect_from_html(html=None):
    """Extract redirect target URL from raw HTML when JS doesn't execute.
    Searches for window.location assignments, meta refresh, and external links.
    Returns the first valid external URL found, or empty string."""
    if html is None:
        html = get_raw_html(8000)
    if not html:
        return ""
    current_domain = ""
    cur = safe_url()
    if cur and "/" in cur:
        current_domain = cur.split("/")[2]
    loc_patterns = [
        r'window\.location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'window\.location\.replace\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        r'window\.location\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'window\.parent\.location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'window\.top\.location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
    ]
    for pat in loc_patterns:
        matches = re.findall(pat, html, re.IGNORECASE)
        for m in matches:
            if not m:
                continue
            if m.startswith('/') and current_domain:
                m = f"https://{current_domain}{m}"
            if m.startswith('http') and 'about:' not in m and 'javascript:' not in m:
                log(f"found redirect in raw HTML: {m[:80]}")
                return m
    meta_match = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\']+)["\']', html, re.IGNORECASE)
    if meta_match:
        url = meta_match.group(1).strip()
        if url.startswith('/') and current_domain:
            url = f"https://{current_domain}{url}"
        if url.startswith('http'):
            log(f"found meta refresh redirect: {url[:80]}")
            return url
    link_matches = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', html, re.IGNORECASE)
    for m in link_matches:
        if not m or m.startswith('#') or m.startswith('javascript:'):
            continue
        if any(d in m for d in AD_NETWORK_DOMAINS):
            continue
        if m.startswith('/') and current_domain:
            m = f"https://{current_domain}{m}"
        if m.startswith('http') and current_domain not in m:
            log(f"found external link in raw HTML: {m[:80]}")
            return m
    return ""


def report_proxy_failure(reason):
    global proxy_failures, proxy_blocked, proxy_punished
    if not PROXY_IP:
        return
    proxy_failures += 1
    log(f"proxy failure #{proxy_failures}: {reason} ({PROXY_IP}:{PROXY_PORT})")
    if not proxy_punished and PROXY_PORT:
        proxy_punished = True
        try:
            mark_dead(PROXY_IP, PROXY_PORT, reason)
        except Exception:
            pass


def _signal_handler(sig, frame):
    global driver
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    if ADS_POWER:
        _ads_power_stop()
    sys.exit(130)


signal.signal(signal.SIGINT, _signal_handler)


# ══════════════════════════════════════════════════════════════
#  AdaptiveTimeout — learns navigation/load/redirect timings
# ══════════════════════════════════════════════════════════════

class AdaptiveTimeout:
    __slots__ = ('name', 'value', 'default', 'min_val', 'max_val', 'safety')

    def __init__(self, name, default, safety=3, min_ratio=0.25, max_ratio=10, hard_max=None):
        self.name = name
        self.value = float(default)
        self.default = float(default)
        self.min_val = float(default * min_ratio)
        self.max_val = float(default * max_ratio)
        if hard_max is not None:
            self.max_val = min(self.max_val, float(hard_max))
        self.safety = float(safety)

    def get(self):
        return self.value

    def observe(self, elapsed):
        target = max(elapsed * self.safety, self.default)
        target = max(self.min_val, min(self.max_val, target))
        self.value = self.value * 0.7 + target * 0.3

    def timeout_occured(self):
        self.value = min(self.max_val, self.value * 2.0)

    def set_page_load(self, driver):
        driver.set_page_load_timeout(int(self.value * 1.2))

    def reset(self):
        self.value = self.default


adpt_nav = AdaptiveTimeout('nav', 40, safety=2)
adpt_load = AdaptiveTimeout('load', 30, safety=2)
adpt_redirect = AdaptiveTimeout('redirect', 25, safety=3, hard_max=30)
adpt_poll = AdaptiveTimeout('poll', 30, safety=3)


# ══════════════════════════════════════════════════════════════
#  PageMonitor — real-time MutationObserver + Network interceptors
# ══════════════════════════════════════════════════════════════

_MONITOR_JS = r"""
(function() {
    if (window.__monetag_monitor) return;
    window.__monetag_monitor = true;
    window.__monetag_events = [];
    window.__monetag_snap = {};

    function pushEvent(type, detail) {
        window.__monetag_events.push({
            type: type, time: Date.now(), detail: detail || {}
        });
        if (window.__monetag_events.length > 200) {
            window.__monetag_events = window.__monetag_events.slice(-200);
        }
    }

    var lastUrl = location.href;
    var observer = new MutationObserver(function(mutations) {
        var changed = false;
        var addedNodes = [];
        var removedNodes = [];
        var attrChanges = [];
        for (var i = 0; i < mutations.length; i++) {
            var m = mutations[i];
            if (m.type === 'childList') {
                for (var j = 0; j < m.addedNodes.length; j++) {
                    var n = m.addedNodes[j];
                    if (n.nodeType === 1) {
                        addedNodes.push(n.tagName + (n.id ? '#' + n.id : '') + (n.className ? '.' + String(n.className).split(' ').join('.') : ''));
                    }
                }
                for (var j = 0; j < m.removedNodes.length; j++) {
                    var n = m.removedNodes[j];
                    if (n.nodeType === 1) {
                        removedNodes.push(n.tagName + (n.id ? '#' + n.id : '') + (n.className ? '.' + String(n.className).split(' ').join('.') : ''));
                    }
                }
                changed = true;
            }
            if (m.type === 'attributes') {
                attrChanges.push({ el: m.target.tagName + (m.target.id ? '#' + m.target.id : ''), attr: m.attributeName });
                changed = true;
            }
        }
        if (changed) {
            pushEvent('dom_mutation', {
                added: addedNodes.slice(0, 10), removed: removedNodes.slice(0, 10), attrs: attrChanges.slice(0, 10)
            });
        }
        if (location.href !== lastUrl) {
            var oldUrl = lastUrl;
            lastUrl = location.href;
            pushEvent('url_change', { from: oldUrl, to: location.href });
        }
    });

    observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true,
        attributeFilter: ['style', 'class', 'href', 'disabled', 'onclick']
    });

    var origFetch = window.fetch;
    window.fetch = function() {
        var url = arguments[0];
        var method = (arguments[1] && arguments[1].method) || 'GET';
        pushEvent('net_request', { url: String(url).substring(0, 200), method: method });
        return origFetch.apply(this, arguments).then(function(resp) {
            pushEvent('net_response', { url: String(url).substring(0, 200), status: resp.status, ok: resp.ok });
            return resp;
        }).catch(function(err) {
            pushEvent('net_error', { url: String(url).substring(0, 200), error: String(err) });
            throw err;
        });
    };

    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._monetag_url = url;
        this._monetag_method = method;
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        var self = this;
        var url = this._monetag_url || '';
        pushEvent('net_request', { url: String(url).substring(0, 200), method: this._monetag_method || 'GET' });
        this.addEventListener('load', function() {
            pushEvent('net_response', { url: String(url).substring(0, 200), status: self.status, ok: self.status >= 200 && self.status < 400 });
        });
        this.addEventListener('error', function() {
            pushEvent('net_error', { url: String(url).substring(0, 200), error: 'network error' });
        });
        return origSend.apply(this, arguments);
    };

    window.addEventListener('beforeunload', function() {
        pushEvent('navigation', { url: location.href, type: 'beforeunload' });
    });

    setInterval(function() {
        var snap = {};
        try {
            snap.bodyLen = (document.body ? document.body.textContent : '').length;
            snap.height = document.documentElement ? document.documentElement.scrollHeight : 0;
            snap.elCount = document.querySelectorAll('*').length;
            snap.readyState = document.readyState;
            snap.title = document.title;
            snap.url = location.href;
            snap.links = document.querySelectorAll('a').length;
            snap.imgs = document.querySelectorAll('img').length;
            snap.forms = document.querySelectorAll('form').length;
            snap.buttons = document.querySelectorAll('button, [role="button"], input[type="submit"]').length;
            snap.scripts = document.querySelectorAll('script').length;
            var req = 0;
            try { req = (performance.getEntriesByType('resource') || []).length; } catch(e) {}
            snap.resources = req;
        } catch(e) {}
        window.__monetag_snap = snap;
    }, 500);

    pushEvent('monitor_installed', {});
})();
"""


class PageMonitor:
    """Real-time page monitor using MutationObserver + Network Interceptors."""
    __slots__ = ('_driver', '_events', '_snap', '_lock', '_installed')

    def __init__(self):
        self._events = []
        self._snap = {}
        self._lock = __import__('threading').Lock()
        self._installed = False

    def install(self, drv):
        self._driver = drv
        try:
            drv.execute_script(_MONITOR_JS)
            self._installed = True
            log("PageMonitor: MutationObserver + Network interceptors installed")
        except Exception as e:
            log(f"PageMonitor: install failed: {e}")

    def poll(self):
        if not self._installed or not self._driver:
            return
        try:
            raw = self._driver.execute_script(
                "var e = window.__monetag_events || []; window.__monetag_events = []; return JSON.stringify(e);"
            )
            if raw:
                new_events = json.loads(raw)
                if new_events:
                    with self._lock:
                        self._events.extend(new_events)
                snap_raw = self._driver.execute_script("return JSON.stringify(window.__monetag_snap || {});")
                if snap_raw:
                    self._snap = json.loads(snap_raw)
        except Exception:
            pass

    def snapshot(self):
        self.poll()
        with self._lock:
            return dict(self._snap) if self._snap else {}

    def events(self, event_type=None, last_sec=None):
        self.poll()
        with self._lock:
            evts = list(self._events)
        if event_type:
            evts = [e for e in evts if e.get("type") == event_type]
        if last_sec:
            cutoff = (time.time() - last_sec) * 1000
            evts = [e for e in evts if e.get("time", 0) >= cutoff]
        return evts

    def net_activity(self, last_sec=5):
        return bool(self.events("net_request", last_sec)) or bool(self.events("net_response", last_sec))


monitor = PageMonitor()


# ══════════════════════════════════════════════════════════════
#  Human-like behavior
# ══════════════════════════════════════════════════════════════

def human_delay(min_ms, max_ms):
    ms(rand(min_ms, max_ms))


_pointer = [0, 0]


def bezier_move(from_x, from_y, to_x, to_y):
    steps = rand(15, 35)
    start_x, start_y = _pointer[0], _pointer[1]
    target_x = start_x + (to_x - from_x)
    target_y = start_y + (to_y - from_y)
    cp1x = start_x + (target_x - start_x) * 0.3 + (random.random() - 0.5) * 80
    cp1y = start_y + (target_y - start_y) * 0.3 + (random.random() - 0.5) * 80
    cp2x = start_x + (target_x - start_x) * 0.7 + (random.random() - 0.5) * 60
    cp2y = start_y + (target_y - start_y) * 0.7 + (random.random() - 0.5) * 60
    prev_x, prev_y = start_x, start_y
    try:
        for i in range(1, steps + 1):
            t = i / steps
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt
            x = mt3 * start_x + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * target_x
            y = mt3 * start_y + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * target_y
            dx, dy = int(x - prev_x), int(y - prev_y)
            if dx or dy:
                ActionChains(driver).move_by_offset(dx, dy).perform()
            prev_x, prev_y = x, y
            _pointer[0], _pointer[1] = int(x), int(y)
            ms(rand(5, 20))
    except Exception:
        pass


def random_click(allow_cross=False):
    """Click a random visible interactive element (link/button) like a human.
    With allow_cross=True, also clicks links that point off the current domain."""
    try:
        same_domain_js = """
                    if (e.tagName === 'A') {
                        if (!e.href || e.href.indexOf('javascript:') === 0) return false;
                        try {
                            var u = new URL(e.href, location.href);
                            var rd = function(h) { var p = h.split('.'); return p.length > 2 ? p.slice(-2).join('.') : h; };
                            if (rd(u.hostname) !== rd(location.hostname)) return false;
                        } catch (err) { return false; }
                    }
"""
        cds = safe_eval(r"""
            var els = Array.from(document.querySelectorAll(
                'a, button, [role="button"], input[type="submit"], .btn, [onclick]'))
                .filter(function(e) {
                    var r = e.getBoundingClientRect();
                    if (!r || r.width < 5 || r.height < 5) return false;
                    if (r.top < -20 || r.bottom > window.innerHeight + 20) return false;
                    var s = getComputedStyle(e);
                    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') return false;
""" + ("" if allow_cross else same_domain_js) + r"""
                    return true;
                })
                .map(function(e) {
                    var r = e.getBoundingClientRect();
                    return {tag: e.tagName,
                            text: (e.innerText || e.value || '').trim().slice(0, 40),
                            x: Math.round(r.left + r.width / 2),
                            y: Math.round(r.top + r.height / 2)};
                });
            return JSON.stringify(els);
        """)
        els = json.loads(cds or "[]")
        if not els:
            return None
        el = random.choice(els)
        x, y = int(el["x"]), int(el["y"])
        human_delay(250, 700)
        bezier_move(0, 0, x, y)
        human_delay(100, 350)
        ActionChains(driver).click().perform()
        log(f"random click: {el['tag']} '{el['text']}' @({x},{y})")
        return el
    except Exception:
        return None


def human_scroll():
    scrolls = rand(1, 3)
    for _ in range(scrolls):
        safe_eval(f"window.scrollBy({{top: {rand(100, 400)}, behavior: 'smooth'}})")
        human_delay(300, 800)


def human_read(duration_sec=20, known_height=0):
    """Simulate human reading with keyboard scrolling."""
    dur = min(duration_sec or 20, 60)
    read_start = time.time()
    start_url = safe_url()
    try:
        max_scroll = safe_eval("return document.documentElement.scrollHeight;") or 0
    except Exception:
        max_scroll = 0
    if max_scroll < 200 and known_height > 200:
        max_scroll = known_height
    if max_scroll < 200:
        for _ in range(3):
            ms(1000)
        return
    try:
        scroll_count = rand(8, 20)
        clicked_any = False
        for i in range(scroll_count):
            if time.time() - read_start >= dur:
                break
            if safe_url() != start_url:
                log("human read: page navigated, stopping")
                break
            at_bottom = safe_eval("return (window.innerHeight + window.scrollY) >= document.documentElement.scrollHeight - 50;") or False
            if at_bottom:
                if random.random() < 0.3:
                    safe_eval("window.scrollBy(0, -200);")
                    ms(rand(800, 1500))
                else:
                    break
            else:
                if random.random() < 0.2:
                    safe_eval("document.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowDown', keyCode:40, bubbles:true}));")
                    ms(rand(80, 200))
                    safe_eval("document.dispatchEvent(new KeyboardEvent('keyup', {key:'ArrowDown', keyCode:40, bubbles:true}));")
                else:
                    safe_eval("document.dispatchEvent(new KeyboardEvent('keydown', {key:'PageDown', keyCode:34, bubbles:true}));")
                    ms(rand(80, 200))
                    safe_eval("document.dispatchEvent(new KeyboardEvent('keyup', {key:'PageDown', keyCode:34, bubbles:true}));")
            # Random human click on a real interactive element while reading
            if random.random() < 0.45:
                if random_click() is not None:
                    clicked_any = True
                ms(rand(1000, 2500))
            else:
                pause = rand(1500, 4000)
                ms(pause)
        if not clicked_any and time.time() - read_start < dur:
            random_click()
    except Exception as e:
        log(f"human read error: {str(e)[:60]}")


def human_click(selector):
    human_delay(100, 300)
    try:
        el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        el.click()
        return True
    except Exception:
        try:
            return safe_eval(f"""
                var el = document.querySelector({json.dumps(selector)});
                if (el) {{ el.click(); return true; }}
                return false;
            """) or False
        except Exception:
            return False


def _inject_traffic_source():
    referrer = os.environ.get("MONETAG_REFERER", "").strip()
    if not referrer and TRAFFIC_SOURCE in TRAFFIC_REFERRERS:
        referrer = TRAFFIC_REFERRERS[TRAFFIC_SOURCE]
    if not referrer:
        return
    referrer_js = f"""
    Object.defineProperty(document, 'referrer', {{
        get: function() {{ return '{referrer}'; }}
    }});
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": referrer_js})
        driver.execute_script(referrer_js)
        log(f"traffic source: {TRAFFIC_SOURCE} referrer={referrer}")
    except Exception:
        pass


def _add_utm_to_url(url):
    if TRAFFIC_SOURCE not in TRAFFIC_UTM or not TRAFFIC_UTM[TRAFFIC_SOURCE]:
        return url
    if not url or not url.startswith("http"):
        return url
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    utm = dict(TRAFFIC_UTM[TRAFFIC_SOURCE])
    for k, v in utm.items():
        if k not in params:
            params[k] = [v]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


# ══════════════════════════════════════════════════════════════
#  Stealth JS — anti-bot fingerprint masking
# ══════════════════════════════════════════════════════════════

def _build_stealth_js(p):
    return f"""
    (function() {{
        var p = {json.dumps(p)};
        Object.defineProperty(navigator, 'webdriver', {{get: function() {{ return undefined; }} }});
        Object.defineProperty(navigator, 'vendor', {{get: function() {{ return 'Google Inc.'; }} }});

        Object.defineProperty(navigator, 'plugins', {{
            get: function() {{
                var plugins = [];
                if (!p.touch) {{
                    plugins = [
                        {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
                        {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
                        {{name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}}
                    ];
                }}
                plugins.length = p.touch ? 0 : 3;
                plugins.refresh = function() {{}};
                return plugins;
            }}
        }});

        Object.defineProperty(navigator, 'languages', {{get: function() {{ return p.languages; }} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{get: function() {{ return p.hardwareConcurrency; }} }});
        Object.defineProperty(navigator, 'deviceMemory', {{get: function() {{ return p.deviceMemory; }} }});
        Object.defineProperty(navigator, 'platform', {{get: function() {{ return p.platform; }} }});
        // maxTouchPoints is non-configurable once touch emulation is active —
        // CDP already sets it to match p.maxTouchPoints, so leave it alone.

        window.chrome = {{ runtime: {{}}, loadTimes: function() {{}}, csi: function() {{}} }};

        var origPermQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = function(params) {{
            return params.name === 'notifications'
                ? Promise.resolve({{ state: 'denied' }})
                : origPermQuery(params);
        }};

        var getParameterOrig = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return p.webgl.vendor;
            if (param === 37446) return p.webgl.renderer;
            return getParameterOrig.call(this, param);
        }};
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            var getParameter2Orig = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {{
                if (param === 37445) return p.webgl.vendor;
                if (param === 37446) return p.webgl.renderer;
                return getParameter2Orig.call(this, param);
            }};
        }}

        var toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            var ctx = this.getContext('2d');
            if (ctx) {{
                var imageData = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                for (var i = 0; i < imageData.data.length; i += 4) {{
                    imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 100)));
                }}
                ctx.putImageData(imageData, 0, 0);
            }}
            return toDataURL.apply(this, arguments);
        }};
        var getImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function() {{
            var imageData = getImageData.apply(this, arguments);
            for (var i = 0; i < imageData.data.length; i += 4) {{
                imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 50)));
            }}
            return imageData;
        }};

        var origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
        AnalyserNode.prototype.getFloatFrequencyData = function(arr) {{
            origGetFloat.call(this, arr);
            for (var i = 0; i < arr.length; i++) arr[i] += p.audioOffset;
        }};
        var origGetByte = AnalyserNode.prototype.getByteFrequencyData;
        AnalyserNode.prototype.getByteFrequencyData = function(arr) {{
            origGetByte.call(this, arr);
            for (var i = 0; i < arr.length; i++) arr[i] = Math.max(0, Math.min(255, arr[i] + Math.round(p.audioOffset * 1000)));
        }};

        Object.defineProperty(screen, 'width', {{get: function() {{ return p.screen.width; }} }});
        Object.defineProperty(screen, 'height', {{get: function() {{ return p.screen.height; }} }});
        Object.defineProperty(screen, 'availWidth', {{get: function() {{ return p.screen.availWidth; }} }});
        Object.defineProperty(screen, 'availHeight', {{get: function() {{ return p.screen.availHeight; }} }});
        Object.defineProperty(screen, 'colorDepth', {{get: function() {{ return p.colorDepth; }} }});
        Object.defineProperty(screen, 'pixelDepth', {{get: function() {{ return p.colorDepth; }} }});

        if (window.outerWidth === 0) {{
            Object.defineProperty(window, 'outerWidth', {{get: function() {{ return p.screen.availWidth; }} }});
            Object.defineProperty(window, 'outerHeight', {{get: function() {{ return p.screen.availHeight; }} }});
        }}

        if (navigator.connection) {{
            Object.defineProperty(navigator.connection, 'rtt', {{get: function() {{ return Math.round(50 + Math.random() * 100); }} }});
        }}

        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: function() {{ return p.maxTouchPoints; }}
        }});

        // Touch / mobile-device API surface must exist only on emulated mobiles
        if (p.touch) {{
            try {{
                Object.defineProperty(window, 'ontouchstart', {{get: function() {{ return null; }} }});
                Object.defineProperty(window, 'ontouchend', {{get: function() {{ return null; }} }});
                Object.defineProperty(window, 'orientation', {{get: function() {{ return 0; }} }});
                if (!('DeviceOrientationEvent' in window)) window.DeviceOrientationEvent = function() {{}};
                if (!('DeviceMotionEvent' in window)) window.DeviceMotionEvent = function() {{}};
                Object.defineProperty(Navigator.prototype, 'userAgentData', {{
                    get: function() {{
                        var brands = p.userAgent.indexOf('Edg/') >= 0
                            ? [{{brand: 'Microsoft Edge', version: '151'}}, {{brand: 'Chromium', version: '151'}}]
                            : [{{brand: 'Google Chrome', version: '151'}}, {{brand: 'Chromium', version: '151'}}];
                        return {{
                            brands: brands,
                            mobile: true,
                            platform: 'Android',
                            getHighEntropyValues: function() {{ return Promise.resolve({{}}); }},
                            toJSON: function() {{ return {{ brands: brands, mobile: true, platform: 'Android' }}; }}
                        }};
                    }}
                }});
            }} catch (e) {{}}
        }}

        if (navigator.getBattery) {{
            navigator.getBattery = function() {{
                return Promise.resolve({{
                    charging: true, chargingTime: 0, dischargingTime: Infinity,
                    level: 0.5 + Math.random() * 0.5,
                    addEventListener: function() {{}}, removeEventListener: function() {{}}
                }});
            }};
        }}
    }})();
    """


# ══════════════════════════════════════════════════════════════
#  Device selection & IP-based geolocation
# ══════════════════════════════════════════════════════════════

def _pick_device_kind():
    """Return 'desktop'|'mobile'|None. MONETAG_DEVICE forces it; default None
    lets generate_profile roll the 40% desktop / 60% Android split."""
    env = os.environ.get("MONETAG_DEVICE", "").strip().lower()
    if env in ("desktop", "mobile", "android"):
        return "desktop" if env == "desktop" else "mobile"
    legacy = os.environ.get("MONETAG_MOBILE", "")
    if legacy:
        return "desktop" if legacy == "0" else "mobile"
    return None


def _lookup_proxy_geo(ip):
    """Resolve a proxy IP to country/timezone/coords via a free geo API."""
    if not ip or ip in ("127.0.0.1", "localhost", "::1"):
        return None
    import urllib.request
    import urllib.parse
    ip = urllib.parse.quote(ip)
    providers = [
        ("https://ipwho.is/%s", "whois"),
        ("http://ip-api.com/json/%s", "ipapi"),
    ]
    for tmpl, kind in providers:
        try:
            url = tmpl % ip
            req = urllib.request.Request(url, headers={"User-Agent": "monetag/3.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if not data:
                continue
            if kind == "whois":
                if not data.get("success"):
                    continue
                tz = data.get("timezone", {})
                timezone = tz.get("id", "") if isinstance(tz, dict) else str(tz or "")
                return {
                    "country": (data.get("country_code") or "").upper(),
                    "timezone": timezone or None,
                    "lat": data.get("latitude"),
                    "lon": data.get("longitude"),
                }
            else:
                if data.get("status") != "success":
                    continue
                return {
                    "country": (data.get("countryCode") or "").upper(),
                    "timezone": data.get("timezone") or None,
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                }
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════
#  AdsPower Local API — drive one fixed profile, bind proxy per view
# ══════════════════════════════════════════════════════════════

def _ads_power_api(path, params=None):
    """Call the AdsPower Local API. Returns parsed JSON or raises."""
    import urllib.request
    import urllib.parse
    url = ADSPOWER_API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _ads_power_stop():
    try:
        _ads_power_api("/api/v1/browser/stop", {"user_id": ADSPOWER_PROFILE_ID})
    except Exception:
        pass


def _ads_power_start(proxy):
    """Start the fixed AdsPower profile with the session proxy bound via launch
    args. Returns (debuggerAddress, data). The profile's own fingerprint
    (device/OS/TLS) is left untouched — the proxy rides on the command line."""
    _ads_power_stop()
    launch = [f"--proxy-server={proxy}"] if proxy else []
    data = _ads_power_api("/api/v1/browser/start", {
        "user_id": ADSPOWER_PROFILE_ID,
        "open_tabs": 1,
        "ip_tab": 0,
        "launch_args": json.dumps(launch),
    })
    if not data or data.get("code") != 0:
        raise RuntimeError(f"AdsPower start failed: {data}")
    info = data.get("data") or {}
    addr = info.get("debuggerAddress") or (
        f"127.0.0.1:{info.get('debug_port')}" if info.get("debug_port") else "")
    if not addr:
        raise RuntimeError(f"AdsPower returned no debugger address: {data}")
    return addr, info


# ══════════════════════════════════════════════════════════════
#  Driver creation
# ══════════════════════════════════════════════════════════════

def _create_driver():
    global driver, profile
    if ADS_POWER:
        proxy = os.environ.get("MONETAG_PROXY", "")
        addr, info = _ads_power_start(proxy)
        log(f"ads-power profile {ADSPOWER_PROFILE_ID} debugger={addr} proxy={proxy or 'none'}")
        options = Options()
        options.add_experimental_option("debuggerAddress", addr)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.page_load_strategy = "none"
        chromedriver_paths = [
            "/usr/bin/chromedriver",
            "/snap/bin/chromium.chromedriver",
            "/usr/lib/chromium-browser/chromedriver",
            "/usr/lib/chromium/chromedriver",
            "/usr/local/bin/chromedriver",
        ]
        driver = None
        for cpath in chromedriver_paths:
            if os.path.exists(cpath) and _check_native_binary(cpath):
                try:
                    driver = webdriver.Chrome(service=Service(executable_path=cpath), options=options)
                    break
                except Exception:
                    continue
        if driver is None:
            from webdriver_manager.chrome import ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(0)
        try:
            driver.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 1048576})
        except Exception:
            pass
        _inject_traffic_source()
        return
    kind = _pick_device_kind()
    geo = _lookup_proxy_geo(PROXY_IP)
    profile = generate_profile(device_kind=kind, youtube=TRAFFIC_SOURCE == "youtube", geo=geo)
    if geo:
        log(f"ip geo: {geo.get('country')} {geo.get('timezone')}")
    log(f"profile: {profile['deviceKind']} {profile['name']} "
        f"{profile['viewport']['width']}x{profile['viewport']['height']} "
        f"{profile['locale']} {profile['timezone']} hw={profile['hardwareConcurrency']} "
        f"mem={profile['deviceMemory']} dpr={profile['deviceScaleFactor']}")

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-accelerated-2d-canvas")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-automation")
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    vp = profile["viewport"]
    is_mobile = profile["deviceKind"] == "mobile"

    if is_mobile:
        # ChromeDriver native mobile emulation: metrics + UA + touch in one shot
        options.add_experimental_option("mobileEmulation", {
            "deviceMetrics": {
                "width": vp["width"],
                "height": vp["height"],
                "pixelRatio": profile["deviceScaleFactor"],
                "mobile": True,
                "touch": True,
            },
            "userAgent": profile["userAgent"],
        })
    else:
        options.add_argument(f"--window-size={vp['width']},{vp['height']}")
        options.add_argument(f"--user-agent={profile['userAgent']}")

    headless = os.environ.get("MONETAG_HEADLESS") == "1"
    if headless:
        options.add_argument("--headless=new")

    if os.environ.get("CHROMIUM_PATH"):
        options.binary_location = os.environ["CHROMIUM_PATH"]
    else:
        options.binary_location = _detect_chrome_binary()

    if PROXY:
        options.add_argument(f"--proxy-server={PROXY}")

    extra_args = os.environ.get("MONETAG_EXTRA_ARGS", "")
    if extra_args:
        for arg in extra_args.split():
            options.add_argument(arg)

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # "none" load strategy: clicks/execute_script never block on a pending
    # navigation (smartlink pages navigate mid-interaction). The engine polls
    # URLs itself, so navigation state is tracked explicitly.
    options.page_load_strategy = "none"

    chromedriver_paths = [
        "/usr/bin/chromedriver",
        "/snap/bin/chromium.chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/local/bin/chromedriver",
    ]
    driver = None
    for cpath in chromedriver_paths:
        if os.path.exists(cpath) and _check_native_binary(cpath):
            try:
                service = Service(executable_path=cpath)
                driver = webdriver.Chrome(service=service, options=options)
                break
            except Exception:
                continue
    if driver is None:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            cm_path = ChromeDriverManager().install()
            service = Service(executable_path=cm_path)
            driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            for cpath in chromedriver_paths:
                if os.path.exists(cpath):
                    try:
                        service = Service(executable_path=cpath)
                        driver = webdriver.Chrome(service=service, options=options)
                        break
                    except Exception:
                        continue

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(0)

    try:
        driver.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 1048576})
    except Exception:
        pass

    _apply_cdp_profile(profile)

    _inject_traffic_source()

    stealth_js = _build_stealth_js(profile)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    except Exception:
        pass
    driver.execute_script(stealth_js)


def _apply_cdp_profile(profile):
    """Push coherent CDP overrides so the browser matches the emulated device:
    timezone, locale, UA/platform, touch, metrics and (when the proxy IP gave
    coordinates) geolocation."""
    try:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": profile["timezone"]})
    except Exception:
        pass
    try:
        driver.execute_cdp_cmd("Emulation.setLocaleOverride", {"locale": profile["locale"]})
    except Exception:
        pass
    try:
        driver.execute_cdp_cmd("Emulation.setUserAgentOverride", {
            "userAgent": profile["userAgent"], "platform": profile["platform"],
        })
    except Exception:
        pass

    if profile["deviceKind"] == "mobile":
        vp = profile["viewport"]
        scr = profile["screen"]
        try:
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": vp["width"], "height": vp["height"],
                "deviceScaleFactor": profile["deviceScaleFactor"],
                "mobile": True, "screenWidth": scr["width"], "screenHeight": scr["height"],
            })
        except Exception:
            pass
        try:
            driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {
                "enabled": True, "maxTouchPoints": profile["maxTouchPoints"],
            })
        except Exception:
            pass

    if profile.get("geoLat") is not None and profile.get("geoLon") is not None:
        try:
            driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
                "latitude": profile["geoLat"], "longitude": profile["geoLon"], "accuracy": 50,
            })
        except Exception:
            pass


def debug_shot(label):
    if not DEBUG:
        return
    d = Path(__file__).parent / "screenshots"
    d.mkdir(exist_ok=True)
    try:
        driver.save_screenshot(str(d / f"{label}.png"))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  SmartLink classification & redirect chain following
# ══════════════════════════════════════════════════════════════

def hostname_of(url):
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_smartlink_domain(url):
    host = hostname_of(url)
    return any(host == d or host.endswith("." + d) for d in SMARTLINK_DOMAINS)


def is_ad_network_domain(url):
    host = hostname_of(url)
    return any(host == d or host.endswith("." + d) for d in AD_NETWORK_DOMAINS)


def classify_landing(url, snap):
    """Classify the final landing page type for verification evidence."""
    host = hostname_of(url)
    if "play.google.com" in host or "apps.apple.com" in host:
        return "app_store"
    if "t.me" in host or "telegram" in host:
        return "telegram"
    if "wa.me" in host or "whatsapp" in host:
        return "whatsapp"
    if any(k in host for k in ("aff", "click", "track", "redirect", "gateway", "offer")):
        return "affiliate_tracker"
    buttons = snap.get("buttons", 0)
    forms = snap.get("forms", 0)
    links = snap.get("links", 0)
    body_len = snap.get("bodyLen", 0)
    if buttons >= 1 or forms >= 1:
        return "offer_landing"
    if body_len >= 1500 and links >= 10:
        return "content_page"
    if body_len >= 500:
        return "offer_page"
    return "thin_page"


def detect_block_signature():
    """Check page for anti-bot / error signatures. Returns list of hits."""
    hits = []
    html = get_raw_html(4000).lower()
    body = safe_eval("return (document.body ? document.body.textContent : '').toLowerCase();") or ""
    for sig in BLOCK_SIGNATURES:
        if sig in html or sig in body:
            hits.append(sig)
    return hits


def follow_redirect_chain():
    """Follow the SmartLink redirect chain until the URL stabilizes or timeout.
    Returns dict {chain: [...], final_url, on_smartlink, on_ad_network, timed_out,
    cloudflare_seen, hops}."""
    chain = []
    seen = {}
    start = time.time()
    hard_timeout = int(os.environ.get("MONETAG_HARD_TIMEOUT", "60"))
    deadline = start + hard_timeout
    last_url = ""
    stable_for = 0.0
    cloudflare_seen = False
    js_redirect_handled = False

    while time.time() < deadline:
        cur = safe_url()
        if cur and cur not in ("about:blank",) and not cur.startswith("chrome-error://"):
            if cur != last_url:
                key = cur.split("?")[0].split("#")[0]
                seen[key] = seen.get(key, 0) + 1
                if seen[key] <= 8:
                    chain.append(cur)
                    last_url = cur
                    log(f"chain hop {len(chain)}: {cur[:110]}")
                    stable_for = 0.0
            else:
                stable_for += 0.7

        # JS redirect fallback: page loaded but stuck on smartlink/ad domain
        if last_url and is_smartlink_domain(last_url) and stable_for >= 3 and not js_redirect_handled:
            html = get_raw_html(5000)
            redirect = extract_redirect_from_html(html)
            if redirect:
                log(f"JS redirect found in raw HTML: {redirect[:80]}")
                try:
                    adpt_load.set_page_load(driver)
                    driver.get(redirect)
                    js_redirect_handled = True
                except Exception:
                    pass
                stable_for = 0.0
                continue

        # Detect Cloudflare challenge (classic browser check + Turnstile)
        if last_url and stable_for >= 2:
            cf = safe_eval("""
                var html = (document.documentElement?.innerHTML || '').substring(0, 3000);
                var url = location.href || '';
                return html.indexOf('cf-browser-verification') >= 0
                    || html.indexOf('challenge-form') >= 0
                    || html.indexOf('cf-challenge') >= 0
                    || html.indexOf('_cf_chl_opt') >= 0
                    || html.indexOf('Checking your browser') >= 0
                    || html.indexOf('turnstile') >= 0
                    || url.indexOf('challenges.cloudflare.com') >= 0
                    || url.indexOf('__cf_chl_tk') >= 0;
            """)
            if cf:
                cloudflare_seen = True
                log("Cloudflare challenge detected (browser check / Turnstile), refreshing once...")
                try:
                    driver.refresh()
                except Exception:
                    pass
                time.sleep(3)
                stable_for = 0.0
                continue

        # Stability check: same URL for ~6s with content → chain done
        if last_url and stable_for >= 6:
            ready, h, bl = wait_for_page_ready(min_height=100, timeout_sec=6)
            snap = monitor.snapshot()
            body_len = snap.get("bodyLen", bl)
            if body_len > 100 or ready:
                log(f"redirect chain stable at hop {len(chain)}: {last_url[:100]}")
                break
            if body_len <= 100 and is_smartlink_domain(last_url):
                # empty smartlink page — one more JS redirect attempt
                html = get_raw_html(5000)
                redirect = extract_redirect_from_html(html)
                if redirect:
                    log(f"empty smartlink page, extracted redirect: {redirect[:80]}")
                    try:
                        driver.get(redirect)
                    except Exception:
                        pass
                    stable_for = 0.0
                    continue

        # Move mouse periodically for human-like behavior during waits
        if len(chain) >= 1 and stable_for > 1:
            pass

        ms(700)

    timed_out = time.time() >= deadline
    final_url = safe_url()
    return {
        "chain": chain,
        "final_url": final_url,
        "on_smartlink": is_smartlink_domain(final_url) if final_url else True,
        "on_ad_network": is_ad_network_domain(final_url) if final_url else True,
        "timed_out": timed_out,
        "cloudflare_seen": cloudflare_seen,
        "hops": len(chain),
    }


def scan_tabs_for_view():
    """Scan all open tabs and pick the most content-rich non-blank, non-ad tab.
    SmartLink landing pages often open popunder/popup tabs. The genuine view
    lives wherever the offer page rendered."""
    best = {"url": "", "score": -1, "handle": None}
    try:
        handles = driver.window_handles
    except Exception:
        return best["url"], best["handle"]
    main_handle = driver.current_window_handle
    for h in handles:
        try:
            driver.switch_to.window(h)
            cur = safe_url()
            if not cur or cur == "about:blank" or cur.startswith("chrome-error://"):
                continue
            if is_ad_network_domain(cur):
                continue
            snap = monitor.snapshot() if h == main_handle else {}
            if not snap or h != main_handle:
                body_len = get_body_text_length()
                height = get_page_height()
                buttons = safe_eval("return document.querySelectorAll('button, [role=\"button\"]').length;") or 0
                links = safe_eval("return document.querySelectorAll('a').length;") or 0
                snap = {"bodyLen": body_len, "height": height, "buttons": buttons, "links": links, "readyState": "unknown"}
            score = snap.get("bodyLen", 0) + snap.get("links", 0) * 5 + snap.get("buttons", 0) * 20
            if score > best["score"]:
                best = {"url": cur, "score": score, "handle": h}
        except Exception:
            continue
    try:
        driver.switch_to.window(main_handle)
    except Exception:
        pass
    return best["url"], best["handle"]


# ══════════════════════════════════════════════════════════════
#  Adaptive page engagement — tap buttons, chase tabs, scroll
# ══════════════════════════════════════════════════════════════

INTERSTITIAL_EXACT = ("continue", "allow", "ok", "open", "start", "play", "watch",
                      "yes", "submit", "skip", "dismiss", "close", "got it", "accept",
                      "enable", "agree", "proceed", "next", "enter", "visit", "understand",
                      "x", "×", "no thanks", "let's go", "let’s go")
INTERSTITIAL_SUBSTR = ("continue", "allow", "accept", "got it", "open", "start", "play",
                       "watch", "enable", "proceed", "submit", "agree", "visit", "enter",
                       "next", "ok", "yes", "dismiss", "skip", "close", "no thanks",
                       "let's go", "let’s go", "admit", "understand", "click to")


def _visible_clickables(max_n=80):
    """Return visible interactive elements: {tag, text, x, y, w, same}."""
    cds = safe_eval(r"""
        var out = [];
        var els = document.querySelectorAll(
            'a, button, [role="button"], input[type="button"], input[type="submit"], ' +
            '.btn, .button, .cta, [onclick], [class*="close"], [class*="continue"], [class*="allow"]');
        for (var i = 0; i < els.length && out.length < __MAXN__; i++) {
            var e = els[i];
            var r = e.getBoundingClientRect();
            if (!r || r.width < 5 || r.height < 5) continue;
            if (r.top < -20 || r.bottom > window.innerHeight + 20) continue;
            var s = getComputedStyle(e);
            if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') continue;
            var same = true;
            if (e.tagName === 'A' && e.href) {
                try {
                    var u = new URL(e.href, location.href);
                    var rd = function(h) { var p = h.split('.'); return p.length > 2 ? p.slice(-2).join('.') : h; };
                    same = rd(u.hostname) === rd(location.hostname);
                } catch (err) { same = true; }
            }
            out.push({tag: e.tagName,
                      text: (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 50),
                      x: Math.round(r.left + r.width / 2),
                      y: Math.round(r.top + r.height / 2),
                      w: Math.round(r.width),
                      same: same});
        }
        return JSON.stringify(out);
    """.replace("__MAXN__", str(max_n)))
    try:
        return json.loads(cds or "[]")
    except Exception:
        return []


def _click_at(x, y):
    try:
        human_delay(300, 800)
        bezier_move(0, 0, int(x), int(y))
        human_delay(100, 350)
        ActionChains(driver).click().perform()
        return True
    except Exception:
        return False


def _click_interstitial():
    """Tap a Continue/Allow/OK/Open-style CTA or dismiss button. Returns True if tapped."""
    els = _visible_clickables()
    if not els:
        return False
    low = [e for e in els if e["text"].lower() in INTERSTITIAL_EXACT]
    if low:
        el = random.choice(low)
    else:
        hits = [e for e in els if e["text"].lower() and
                any(k in e["text"].lower() for k in INTERSTITIAL_SUBSTR)]
        if not hits:
            return False
        hits.sort(key=lambda e: (e["w"], not e["same"]))
        el = hits[0]
    if _click_at(el["x"], el["y"]):
        log(f"interstitial tap: '{el['text']}' ({el['tag']}) @({el['x']},{el['y']})")
        return True
    return False


def _switch_to_best_tab():
    """Switch to the most content-rich non-ad tab (popunder offer tab)."""
    url, h = scan_tabs_for_view()
    if h:
        try:
            if driver.current_window_handle != h:
                driver.switch_to.window(h)
                log(f"chased tab: {(url or '')[:100]}")
            return url
        except Exception:
            return None
    return None


def engage_with_page(duration_sec, known_height=0):
    """Adaptively interact with whatever the SmartLink served: tap CTA buttons,
    chase popunder/offer tabs, scroll, click real elements — so the automation
    follows random ads/offers instead of passively waiting. Returns the best
    landing URL + handle found."""
    dur = min(duration_sec or 20, 60)
    start = time.time()
    last_tab_check = 0.0
    best_url = safe_url()
    best_handle = None
    navigated = False
    while time.time() - start < dur:
        # leave enough time for verify (watchdog protects hard hangs)
        if time.time() - start >= dur - 6:
            break
        # 1. Chase any newly-opened content tab (popunder offer)
        if time.time() - last_tab_check > 4:
            url = _switch_to_best_tab()
            if url and url != "about:blank":
                best_url = url
                try:
                    best_handle = driver.current_window_handle
                except Exception:
                    pass
            last_tab_check = time.time()
            navigated = False
        if safe_url() != best_url:
            best_url = safe_url()
            navigated = False
        # 2. Page changed? tap a CTA / dismiss interstitial
        if not navigated and _click_interstitial():
            navigated = True
            ms(rand(800, 2000))
            continue
        # 3. Scroll + random click on real elements
        if random.random() < 0.5:
            random_click(allow_cross=(random.random() < 0.15))
            ms(rand(900, 2200))
        else:
            human_scroll()
            ms(rand(1200, 2800))
        if safe_url() != best_url:
            best_url = safe_url()
    return best_url, best_handle


# ══════════════════════════════════════════════════════════════
#  View verification — multi-signal scoring
# ══════════════════════════════════════════════════════════════

def verify_view(chain_info, landing_url, dwell_secs):
    """Score a view using weighted signals. Returns (record, score, verdict)."""
    snap = monitor.snapshot()
    ready = safe_eval("return document.readyState;") or ""
    body_len = snap.get("bodyLen", get_body_text_length())
    height = snap.get("height", get_page_height())
    el_count = snap.get("elCount", 0)
    links = snap.get("links", 0)
    imgs = snap.get("imgs", 0)
    forms = snap.get("forms", 0)
    buttons = snap.get("buttons", 0)
    resources = snap.get("resources", 0)
    js_ok = verify_js_working()
    block_hits = detect_block_signature()
    landing_type = classify_landing(landing_url, snap)

    signals = {}

    # S1. left_network (20)
    if chain_info.get("on_smartlink"):
        # Offer rendered inline on the smartlink domain itself (no redirect)
        if body_len >= 300 and el_count >= 20:
            signals["left_network"] = 8
        else:
            signals["left_network"] = 5
    elif chain_info.get("on_ad_network"):
        signals["left_network"] = 0
    elif chain_info.get("hops", 0) >= 1:
        signals["left_network"] = 20
    else:
        signals["left_network"] = 10

    # S2. page_rendered (20)
    rendered = 0
    if ready == "complete" and body_len >= 300 and el_count >= 50:
        rendered = 20
    elif body_len >= 500:
        rendered = 16
    elif body_len >= 200:
        rendered = 10
    elif body_len >= 50:
        rendered = 4
    signals["page_rendered"] = rendered

    # S3. js_healthy (10)
    signals["js_healthy"] = 10 if js_ok else 0

    # S4. not_blocked (15)
    if block_hits:
        signals["not_blocked"] = 0
        log(f"BLOCK SIGNALS DETECTED: {block_hits}")
    elif chain_info.get("cloudflare_seen"):
        signals["not_blocked"] = 8
    elif body_len < 50 and height > 500:
        signals["not_blocked"] = 2  # CSS shell — JS content blocked
    elif body_len < 100:
        signals["not_blocked"] = 5
    else:
        signals["not_blocked"] = 15

    # S5. offer_signals (15)
    offer = 0
    if landing_type in ("app_store", "telegram", "whatsapp"):
        offer = 15
    elif landing_type == "offer_landing":
        offer = 15
    elif landing_type in ("affiliate_tracker",):
        offer = 11
    elif landing_type == "content_page":
        offer = 9
    elif landing_type == "offer_page":
        offer = 7
    else:
        offer = 2
    if buttons >= 1 and offer < 15:
        offer = min(15, offer + 3)
    signals["offer_signals"] = offer

    # S6. network_evidence (10)
    net = 0
    net_active = monitor.net_activity(last_sec=30)
    if resources >= 15:
        net = 10
    elif resources >= 8:
        net = 8
    elif resources >= 3:
        net = 5
    elif net_active:
        net = 3
    signals["network_evidence"] = net

    # S7. dwell_time (10)
    dwell_score = min(10, int(dwell_secs))
    signals["dwell_time"] = dwell_score

    score = 0
    for k, w in VIEW_WEIGHTS.items():
        score += int(round(w * (signals[k] / w)))

    if VERIFY_MODE == "lenient":
        thresholds = [(80, "VIEW_VERIFIED"), (55, "VIEW_LIKELY"), (30, "VIEW_WEAK"), (10, "VIEW_BLOCKED")]
    else:
        thresholds = [(85, "VIEW_VERIFIED"), (65, "VIEW_LIKELY"), (45, "VIEW_WEAK"), (20, "VIEW_BLOCKED")]
    verdict = "VIEW_INVALID"
    for thresh, v in thresholds:
        if score >= thresh:
            verdict = v
            break

    record = {
        "smartlink_url": SMARTLINK_URL,
        "final_url": landing_url,
        "landing_type": landing_type,
        "chain_hops": chain_info.get("chain", []),
        "hops": chain_info.get("hops", 0),
        "cloudflare_seen": chain_info.get("cloudflare_seen", False),
        "signals": signals,
        "page_stats": {
            "readyState": ready, "body_len": body_len, "height": height,
            "elements": el_count, "links": links, "images": imgs,
            "forms": forms, "buttons": buttons, "resources": resources,
            "js_working": js_ok,
        },
        "block_signatures": block_hits,
        "score": score,
        "verdict": verdict,
        "verify_mode": VERIFY_MODE,
        "dwell_secs": dwell_secs,
        "proxy_ip": PROXY_IP,
        "profile": {
            "ua": profile["userAgent"] if profile else "",
            "viewport": profile["viewport"] if profile else {},
            "geo": profile.get("geo", "") if profile else "",
        },
        "traffic_source": TRAFFIC_SOURCE,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return record, score, verdict


# ══════════════════════════════════════════════════════════════
#  View cycle — one full SmartLink visit
# ══════════════════════════════════════════════════════════════

def start_cycle_watchdog(deadline, driver_instance):
    """Enforce the per-cycle hard deadline against blocking WebDriver calls.

    A slow/unresponsive page over a proxy can block execute_script/get for a
    long time, silently defeating the per-view budget (safe_eval has no
    timeout). Quitting the driver from a daemon thread unblocks the pending
    command so the cycle wraps up within budget (as an invalid view) instead
    of hanging the whole attempt."""
    def _watch():
        while time.time() < deadline + 8:
            time.sleep(0.5)
        try:
            if driver_instance is not None:
                log(f"cycle watchdog: hard deadline passed, force-quitting driver")
                driver_instance.quit()
        except Exception:
            pass
    threading.Thread(target=_watch, daemon=True).start()


def run_view_cycle(cycle_idx):
    """Run one full SmartLink view cycle. Returns (record, exit_code) or (None, code)."""
    global driver, proxy_blocked, PROXY, PROXY_IP, PROXY_PORT, monitor

    _create_driver()
    monitor = PageMonitor()
    monitor.install(driver)
    cycle_start = time.time()
    hard_timeout = int(os.environ.get("MONETAG_HARD_TIMEOUT", "60"))
    cycle_deadline = cycle_start + hard_timeout
    start_cycle_watchdog(cycle_deadline, driver)

    # Navigate to SmartLink
    nav_url = _add_utm_to_url(SMARTLINK_URL)
    log(f"[view {cycle_idx + 1}] navigating SmartLink: {nav_url[:110]}")
    try:
        adpt_load.set_page_load(driver)
        ns = time.time()
        driver.get(nav_url)
        adpt_nav.observe(time.time() - ns)
    except Exception as e:
        log(f"smartlink nav failed: {e}")

    human_delay(1500, 3000)
    debug_shot(f"view{cycle_idx + 1}-start")

    # page_load_strategy=none → driver.get returns immediately; poll until the
    # smartlink navigation actually starts (redirect may kick in right away)
    nav_wait = time.time()
    first_url = safe_url()
    while time.time() - nav_wait < 12:
        if first_url and first_url != "about:blank" and not first_url.startswith("chrome-error://"):
            break
        ms(500)
        first_url = safe_url()

    # Wait for first real page (redirect may start immediately)
    if not first_url or first_url == "about:blank" or first_url.startswith("chrome-error://"):
        log(f"no usable page after smartlink nav: {first_url or 'blank'}")
        report_proxy_failure("smartlink-nav-empty")
        driver.quit()
        driver = None
        if ADS_POWER:
            _ads_power_stop()
        return None, 2

    # Follow the redirect chain
    chain_info = follow_redirect_chain()
    debug_shot(f"view{cycle_idx + 1}-chain")

    # Pick the view tab (offer may have opened a new tab)
    landing_url, view_handle = scan_tabs_for_view()
    if not landing_url or landing_url == "about:blank":
        landing_url = safe_url()
    if view_handle:
        try:
            driver.switch_to.window(view_handle)
        except Exception:
            pass
    log(f"view target URL: {(landing_url or '')[:110]}")

    # Re-install PageMonitor on the landing document — the redirect chain
    # navigated to a fresh page, wiping the observer + snapshot from the
    # smartlink document.
    try:
        monitor.install(driver)
        ms(1500)
    except Exception:
        pass

    # Dwell — adaptive engagement: tap CTA/interstitial buttons, chase offer
    # tabs, scroll, click real elements (SmartLink serves random ads/offers
    # that only resolve with real interaction). Capped to fit the cycle budget.
    dwell_secs = rand(10, 25)
    remaining = cycle_deadline - time.time()
    dwell_secs = max(1, min(dwell_secs, int(remaining) - 8))
    snap = monitor.snapshot()
    known_height = snap.get("height", 0)
    engaged_url, engaged_handle = engage_with_page(dwell_secs, known_height)
    if engaged_handle:
        landing_url = engaged_url or landing_url
        try:
            driver.switch_to.window(engaged_handle)
        except Exception:
            pass
    # Re-install PageMonitor on the final landing document
    try:
        monitor.install(driver)
        ms(1200)
    except Exception:
        pass

    # Verify
    record, score, verdict = verify_view(chain_info, landing_url, dwell_secs)
    elapsed = time.time() - cycle_start
    log(f"[view {cycle_idx + 1}] verdict={verdict} score={score} "
        f"type={record['landing_type']} hops={chain_info.get('hops', 0)} elapsed={elapsed:.0f}s")

    if verdict in ("VIEW_BLOCKED", "VIEW_INVALID"):
        proxy_blocked = True
        if PROXY:
            report_proxy_failure(f"view-{verdict.lower()}")

    if PROXY_IP and PROXY_PORT:
        mark_proxy_used(PROXY_IP, PROXY_PORT)

    try:
        driver.quit()
    except Exception:
        pass
    driver = None
    if ADS_POWER:
        _ads_power_stop()
    return record, 0


# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def parse_args(argv):
    global SMARTLINK_URL, VIEWS_TOTAL, VERIFY_MODE, TRAFFIC_SOURCE, DEBUG, PROXY, PROXY_IP, PROXY_PORT

    args = list(argv[1:])
    url_arg = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--views" and i + 1 < len(args):
            try:
                VIEWS_TOTAL = max(1, int(args[i + 1]))
            except Exception:
                pass
            i += 2
            continue
        if a == "--verify-mode" and i + 1 < len(args):
            VERIFY_MODE = args[i + 1] if args[i + 1] in ("strict", "lenient") else "strict"
            i += 2
            continue
        if a == "--traffic-source" and i + 1 < len(args):
            TRAFFIC_SOURCE = args[i + 1].lower()
            i += 2
            continue
        if a == "--debug":
            DEBUG = True
            i += 1
            continue
        if not a.startswith("-"):
            url_arg = a
        i += 1

    SMARTLINK_URL = url_arg or os.environ.get("MONETAG_SMARTLINK_URL", "")
    env_views = os.environ.get("MONETAG_VIEWS", "")
    if env_views:
        try:
            VIEWS_TOTAL = max(1, int(env_views))
        except Exception:
            pass
    env_verify = os.environ.get("MONETAG_VERIFY_MODE", "")
    if env_verify in ("strict", "lenient"):
        VERIFY_MODE = env_verify
    env_ts = os.environ.get("MONETAG_TRAFFIC_SOURCE", "")
    if env_ts:
        TRAFFIC_SOURCE = env_ts.lower()
    DEBUG = DEBUG or os.environ.get("MONETAG_DEBUG") == "1"

    PROXY = os.environ.get("MONETAG_PROXY", "")
    PROXY_IP = PROXY.replace("https://", "").replace("http://", "").split(":")[0] if PROXY else ""
    PROXY_PORT = int(PROXY.split(":")[-1]) if PROXY and ":" in PROXY.split("//")[-1] else 0

    if not SMARTLINK_URL:
        print("Usage: python3 monetag_automation.py <smartlink_url> [--views N] [--verify-mode strict|lenient] [--traffic-source ...] [--debug]",
              file=sys.stderr)
        print("       or set MONETAG_SMARTLINK_URL", file=sys.stderr)
        sys.exit(1)

    if not SMARTLINK_URL.startswith("http"):
        SMARTLINK_URL = "https://" + SMARTLINK_URL


def main():
    global SMARTLINK_URL, VIEWS_TOTAL
    parse_args(sys.argv)

    log("=" * 50)
    log(f"Monetag SmartLink automation — views={VIEWS_TOTAL} verify_mode={VERIFY_MODE} "
        f"traffic={TRAFFIC_SOURCE} proxy={bool(PROXY)}")
    if DEBUG:
        log("debug mode active")
    log(f"smartlink: {SMARTLINK_URL[:110]}")

    records = []
    exit_codes = []
    worst = 0

    for cycle in range(VIEWS_TOTAL):
        if cycle > 0:
            # fresh proxy per cycle (rotate)
            if PROXY:
                log(f"--- rotating proxy for view {cycle + 1} ---")
                if get_proxy:
                    try:
                        picked = get_proxy("premium")
                        if picked:
                            os.environ["MONETAG_PROXY"] = f"http://{picked['ip']}:{picked['port']}"
                            PROXY_IP = picked["ip"]
                            PROXY_PORT = int(picked["port"])
                            log(f"new proxy: {PROXY_IP}:{PROXY_PORT}")
                    except Exception as e:
                        log(f"proxy rotation failed: {e}")
        record, code = run_view_cycle(cycle)
        if record:
            records.append(record)
            print(f"VIEW {cycle + 1}: {record['verdict']} score={record['score']} → {record['final_url'][:90]}")
            if record["verdict"] in ("VIEW_BLOCKED", "VIEW_INVALID"):
                worst = max(worst, 2)
            elif record["verdict"] == "VIEW_WEAK":
                worst = max(worst, 3)
            else:
                worst = max(worst, 0)
        else:
            print(f"VIEW {cycle + 1}: FAILED (exit {code})")
            worst = max(worst, 2)
        exit_codes.append(code)
        ms(2000)

    # ── Report ──
    report = {
        "platform": "Monetag",
        "smartlink_url": SMARTLINK_URL,
        "views_requested": VIEWS_TOTAL,
        "views_completed": len(records),
        "verify_mode": VERIFY_MODE,
        "traffic_source": TRAFFIC_SOURCE,
        "summary": {},
        "views": records,
    }
    verdicts = [r["verdict"] for r in records]
    report["summary"] = {
        v: verdicts.count(v) for v in sorted(set(verdicts))
    }
    report["summary"]["total"] = len(records)
    report["summary"]["verified_or_likely"] = sum(1 for r in records if r["verdict"] in ("VIEW_VERIFIED", "VIEW_LIKELY"))
    report["summary"]["landing_types"] = {
        t: sum(1 for r in records if r["landing_type"] == t) for t in sorted(set(r["landing_type"] for r in records))
    }
    report["summary"]["unique_final_domains"] = sorted(set(
        hostname_of(r["final_url"]) for r in records if r["final_url"]
    ))

    out_path = Path(__file__).parent / "view_report.json"
    try:
        out_path.write_text(json.dumps(report, indent=2), "utf-8")
        log(f"view report written to {out_path}")
    except Exception as e:
        log(f"could not write report: {e}")

    print("\n" + "=" * 39)
    print("  MONETAG SMARTLINK VIEW REPORT")
    for k, v in report["summary"].items():
        print(f"  {k}: {v}")
    print("=" * 39)

    sys.exit(worst)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Fatal automation error: {error}", file=sys.stderr)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        if ADS_POWER:
            try:
                _ads_power_stop()
            except Exception:
                pass
        sys.exit(1)
