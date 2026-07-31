import json
import os
import tempfile
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "monetag"
CONFIG_PATH = CONFIG_DIR / "config.json"
PROXY_BLACKLIST_PATH = CONFIG_DIR / "proxy_blacklist.json"

# Migrate from legacy path (~/.monetag3.0/) if it exists and new path doesn't
_LEGACY_DIR = Path.home() / ".monetag3.0"
_LEGACY_CONFIG = _LEGACY_DIR / "config.json"
if _LEGACY_CONFIG.exists() and not CONFIG_PATH.exists():
    try:
        _LEGACY_DIR.rename(CONFIG_DIR)
    except OSError:
        pass

DEFAULTS = {
    "supabase_url": "",
    "supabase_key": "",
    "supabase_secret": "",
    "proxy_enabled": False,
    "proxy_tier": "premium",
    "smartlink_url": "",
    "traffic_source": "direct",
    "verify_mode": "strict",
    "headless": True,
    "random_urls": [],
    "vnc_port": 5900,
    "views": 1,
    "target_geo": "",
}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except Exception:
        pass


def _write_json_secure(filepath, value):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(
        dir=str(CONFIG_DIR), prefix=f"{filepath.name}.", suffix=".tmp"
    )
    try:
        os.write(fd, json.dumps(value, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(filepath))
        try:
            filepath.chmod(0o600)
        except Exception:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def load():
    _ensure_dir()
    try:
        raw = CONFIG_PATH.read_text("utf-8")
        saved = json.loads(raw)
        merged = {**DEFAULTS, **saved}
        return merged
    except Exception:
        return {**DEFAULTS}


def save(config):
    existing = load()
    merged = {**existing, **config}
    _write_json_secure(CONFIG_PATH, merged)
    return merged


def load_proxy_blacklist():
    twenty_four_h = 24 * 60 * 60 * 1000
    now_ms = int(time.time() * 1000)
    try:
        if PROXY_BLACKLIST_PATH.exists():
            raw = PROXY_BLACKLIST_PATH.read_text("utf-8")
            lst = json.loads(raw)
            filtered = []
            for entry in lst:
                if isinstance(entry, dict):
                    ts = entry.get("ts", 0)
                    if ts == 0 or (now_ms - ts) < twenty_four_h:
                        filtered.append(entry.get("key", ""))
                else:
                    filtered.append(str(entry))
            return filtered
    except Exception:
        pass
    return []


def is_configured():
    cfg = load()
    return bool(cfg.get("supabase_url") and cfg.get("supabase_key") and cfg.get("supabase_secret"))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--get":
        cfg = load()
        val = cfg.get(args[1], "")
        print(val if val is not None else "")
    elif len(args) >= 3 and args[0] == "--set":
        key = args[1]
        val_str = " ".join(args[2:])
        if val_str == "true":
            val = True
        elif val_str == "false":
            val = False
        elif val_str.isdigit():
            val = int(val_str)
        else:
            val = val_str
        save({key: val})
    elif len(args) == 1 and args[0] == "--check":
        print("configured" if is_configured() else "unconfigured")
    elif len(args) == 0:
        cfg = load()
        print(json.dumps(cfg, indent=2))
    else:
        print(f"Usage: python3 config.py [--get KEY|--set KEY VALUE|--check]", file=sys.stderr)
        sys.exit(1)
