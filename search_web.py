#!/usr/bin/env python3
"""Local web-search CLI — scrapes public search engines directly (no API keys,
no rate-limited APIs). Rotates DuckDuckGo / Bing / Brave with realistic UA
headers to avoid blocking.

Usage:
    python3 search_web.py "query one" "query two" [...]
    python3 search_web.py --engine ddg --limit 15 --json --out results.json "android fingerprint spoof"
    python3 search_web.py --fetch "https://example.com/article" --out page.txt
    python3 search_web.py --queries-file queries.txt --delay 5

Options:
    --engine auto|ddg|bing|brave   search engine (default auto → rotates per query)
    --limit N                      max results per query (default 10)
    --delay SEC                    pause between requests (default 4)
    --json                         output raw JSON
    --out FILE                     also write results to FILE (.md or .json)
    --fetch URL                    fetch a page and print readable text
    --queries-file FILE            read queries from file (one per line)
    --timeout SEC                  per-request timeout (default 20)
"""

import argparse
import base64
import html as html_mod
import json
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("This script needs `requests`. Install: pip install requests", file=sys.stderr)
    sys.exit(2)

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

SEARCHAPI_KEY = "tMj7oNdMAC4gu3RCGWYhr8zv"

_sess = None

def _session():
    global _sess
    if _sess is None:
        _sess = requests.Session()
        _sess.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    _sess.headers["User-Agent"] = random.choice(UA_POOL)
    return _sess


def _get(url, timeout):
    s = _session()
    resp = s.get(url, timeout=timeout, allow_redirects=True)
    if resp.status_code == 429:
        raise BlockedError("429 Too Many Requests")
    if resp.status_code in (403, 503):
        raise BlockedError(f"HTTP {resp.status_code} (blocked)")
    resp.raise_for_status()
    return resp.text


class BlockedError(Exception):
    pass


def _clean(text):
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _decode_ddg_redirect(href):
    if "duckduckgo.com/l/" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "uddg" in q:
            return q["uddg"][0]
    return href


def _decode_bing_redirect(href):
    if "bing.com/ck/a" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "u" in q:
            try:
                return urllib.parse.unquote(base64.urlsafe_b64decode(q["u"][0] + "==").decode("utf-8"))
            except Exception:
                pass
    return href


def search_searchapi(query, limit, device="desktop"):
    params = {
        "engine": "google",
        "q": query,
        "num": min(limit, 20),
        "device": device,
        "hl": "en",
        "gl": "us",
    }
    resp = requests.get(
        "https://www.searchapi.io/api/v1/search",
        params=params,
        headers={"Authorization": "Bearer " + SEARCHAPI_KEY},
        timeout=30,
    )
    if resp.status_code == 429:
        raise BlockedError("SearchAPI 429 (quota exceeded)")
    if resp.status_code != 200:
        raise BlockedError(f"SearchAPI HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    results = []
    for r in data.get("organic_results", []) or []:
        link = r.get("link") or ""
        if not link or not link.startswith("http"):
            continue
        results.append({
            "title": _clean(r.get("title", "")),
            "url": link,
            "snippet": _clean(r.get("snippet", "")),
        })
        if len(results) >= limit:
            break
    return results


def search_ddg(query, limit):
    s = _session()
    # Warm up the home page to acquire cookies, then POST the query — GET is
    # served a 202 challenge, POST returns real results.
    try:
        s.get("https://duckduckgo.com/", timeout=20)
    except Exception:
        pass
    resp = s.post("https://html.duckduckgo.com/html/",
                  data={"q": query}, timeout=25, allow_redirects=True)
    if resp.status_code in (429, 403, 503) or resp.status_code >= 400:
        raise BlockedError(f"DDG HTTP {resp.status_code}")
    html = resp.text
    blocks = re.split(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>', html)[1:]
    results = []
    for b in blocks:
        m = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        href = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        ms = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', b, re.S)
        snippet = _clean(ms.group(1)) if ms else ""
        url = _decode_ddg_redirect(href)
        if url.startswith("//"):
            url = "https:" + url
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def search_bing(query, limit):
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query) + "&count=" + str(limit)
    html = _get(url, 25)
    results = []
    for b in re.split(r'<li class="b_algo"', html)[1:]:
        m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', b, re.S)
        if not m:
            continue
        href = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        if "bing.com" in href or "microsoft" in href:
            continue
        mp = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
        snippet = _clean(mp.group(1)) if mp else ""
        results.append({"title": title, "url": _decode_bing_redirect(href), "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def search_marginalia(query, limit):
    url = "https://search.marginalia.nu/search?query=" + urllib.parse.quote(query)
    html = _get(url, 25)
    results = []
    for b in re.split(r'<article[^>]*>', html)[1:]:
        m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        href = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        mp = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
        snippet = _clean(mp.group(1)) if mp else ""
        if href.startswith("http"):
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def search_brave(query, limit):
    url = "https://search.brave.com/search?q=" + urllib.parse.quote(query)
    html = _get(url, 25)
    results = []
    for b in re.split(r'class="snippet"', html)[1:]:
        m = re.search(r'<a[^>]*class="[^"]*snippet-title-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        href = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        mp = re.search(r'class="snippet-description[^"]*"[^>]*>(.*?)</p>', b, re.S)
        snippet = _clean(mp.group(1)) if mp else ""
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


ENGINES = {
    "searchapi": search_searchapi,
    "ddg": search_ddg,
    "marginalia": search_marginalia,
    "bing": search_bing,
    "brave": search_brave,
}


def search_one(query, engine, limit, delay):
    if engine == "auto":
        order = ["searchapi", "ddg", "marginalia", "brave", "bing"]
        last_err = None
        for eng in order:
            try:
                res = ENGINES[eng](query, limit)
                if res:
                    return eng, res
            except BlockedError as e:
                last_err = e
            except Exception as e:
                last_err = e
            time.sleep(delay)
        raise last_err or RuntimeError("all engines failed")
    res = ENGINES[engine](query, limit)
    return engine, res


def fetch_page(url, timeout=25):
    html = _get(url, timeout)
    text = _clean(html)
    return url, text


def fmt_md(query, engine, results, idx):
    lines = [f"## [{idx}] {query}", f"_(engine: {engine})_", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"**{i}. {r['title']}**")
        lines.append(r["url"])
        if r.get("snippet"):
            lines.append(f"> {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Local web search (scrapes public engines)")
    ap.add_argument("queries", nargs="*", help="search queries")
    ap.add_argument("--engine", default="auto", choices=list(ENGINES) + ["auto"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--delay", type=float, default=4.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write results to file (.md or .json)")
    ap.add_argument("--fetch", help="fetch a URL and print readable text")
    ap.add_argument("--queries-file", help="read queries from file, one per line")
    ap.add_argument("--timeout", type=float, default=20)
    args = ap.parse_args()

    if args.fetch:
        url, text = fetch_page(args.fetch, args.timeout)
        print(f"# {url}\n")
        print(text[:8000])
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(f"# {url}\n\n{text}")
        return

    queries = list(args.queries)
    if args.queries_file:
        with open(args.queries_file, encoding="utf-8") as f:
            queries.extend(l.strip() for l in f if l.strip())

    if not queries:
        ap.print_help()
        return

    all_data = {"generated_at": datetime.now(timezone.utc).isoformat(), "results": []}
    md_lines = [f"# Web search — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]

    for idx, q in enumerate(queries, 1):
        try:
            engine, res = search_one(q, args.engine, args.limit, args.delay)
        except Exception as e:
            print(f"[search {idx}] '{q}' FAILED: {e}", file=sys.stderr)
            continue
        print(f"[search {idx}] '{q}' ({engine}, {len(res)} results)")
        all_data["results"].append({"query": q, "engine": engine, "results": res})
        md_lines.append(fmt_md(q, engine, res, idx))
        if idx < len(queries):
            time.sleep(args.delay)

    if args.json:
        out = json.dumps(all_data, indent=2, ensure_ascii=False)
    else:
        out = "\n".join(md_lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"written -> {args.out}")
    print(out)


if __name__ == "__main__":
    main()
