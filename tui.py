#!/usr/bin/env python3
"""Monetag Interactive TUI — account, deployment, sync, status, logs, settings."""

import base64, json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.error, zipfile, io
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    import nacl.public
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

# ─── Config ───────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("MONETAG_HOME", os.path.expanduser("~/.monetag247")))
GITHUB_API = "https://api.github.com"
TEMPLATE_REPO = "adittaya/workflow-monetag"
DEPLOY_TIMEOUT = 120
TEMPLATE_MAX_AGE = 3600  # re-pull template if older than 1 hour
API_PER_PAGE = 100
API_MAX_PAGES = 5
GH_TIMEOUT = 30
GIT_TIMEOUT = 60
LOG_MAX_LINES = 80
LOG_MAX_RUNS = 10
WORKFLOW_DISCOVERY_RETRIES = 5
WORKFLOW_ENABLE_DELAY = 5
WORKFLOW_ENABLE_RETRIES = 5
WORKFLOW_ENABLE_RETRY_DELAY = 3

# ─── ANSI Colors ──────────────────────────────────────────────────────────────

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"
C_RED    = "\033[31m"
C_GREEN  = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE   = "\033[34m"
C_CYAN   = "\033[36m"
C_WHITE  = "\033[37m"
C_GRAY   = "\033[90m"
C_BRGREEN = "\033[92m"
C_BRCYAN  = "\033[96m"
C_BRYELLOW = "\033[93m"
C_BRRED  = "\033[91m"
C_BOLDWHITE = "\033[1;37m"

# ─── Data Layer ───────────────────────────────────────────────────────────────

def _data_path(name):
    return DATA_DIR / name

def load_json(name):
    p = _data_path(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def save_json(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _data_path(name).write_text(json.dumps(data, indent=2))

def load_legacy_config():
    """Load Supabase creds from ~/.config/monetag/config.json as fallback."""
    p = Path.home() / ".config" / "monetag" / "config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}

def get_supabase_creds(settings):
    """Get Supabase credentials from settings, falling back to legacy config."""
    su = settings.get("supabase_url", "")
    sk = settings.get("supabase_key", "")
    ss = settings.get("supabase_secret", "")
    if not su:
        legacy = load_legacy_config()
        su = su or legacy.get("supabase_url", "")
        sk = sk or legacy.get("supabase_key", "")
        ss = ss or legacy.get("supabase_secret", "")
    return su, sk, ss

def validate_repo_name(name):
    """Validate GitHub repo name (alphanumeric, hyphens, underscores only)."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))

def normalize_url(val):
    """Auto-fix minor URL mistakes: strip whitespace, add https:// scheme."""
    val = (val or "").strip()
    if not val:
        return ""
    if not re.match(r'^https?://', val, re.I):
        val = "https://" + val
    return val

def looks_like_url(val):
    return bool(val and re.match(r'^https?://\S+\.\S+', val, re.I))

# ─── GitHub API ───────────────────────────────────────────────────────────────

def gh(endpoint, token, method="GET", body=None):
    url = endpoint if endpoint.startswith("http") else f"{GITHUB_API}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "monetag-tui/3.0")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
            raw = resp.read()
            scopes = resp.headers.get("X-OAuth-Scopes", "")
            if not raw:
                return {"ok": True, "status": resp.status, "_scopes": scopes}
            result = json.loads(raw)
            if isinstance(result, dict):
                result["_scopes"] = scopes
            return result
    except urllib.error.HTTPError as e:
        return {"error": True, "status": e.code, "message": e.read().decode(errors="replace")}

def gh_user(token):
    return gh("/user", token)

def paginate_repos(token):
    all_repos = []
    for page in range(1, API_MAX_PAGES + 1):
        repos = gh(f"/user/repos?per_page={API_PER_PAGE}&page={page}&type=all", token)
        if isinstance(repos, dict) and repos.get("error"):
            if repos.get("status") == 403:
                return {"_rate_limited": True}
            break
        if not repos:
            break
        all_repos.extend(repos)
        if len(repos) < API_PER_PAGE:
            break
    return all_repos

def get_monetag_repos(token):
    repos = paginate_repos(token)
    if isinstance(repos, dict) and repos.get("_rate_limited"):
        return repos
    return [r for r in repos if r["name"].startswith("monetag-")]

def get_workflow(owner, repo, token):
    data = gh(f"/repos/{owner}/{repo}/actions/workflows", token)
    if isinstance(data, dict) and data.get("error"):
        return None
    for w in data.get("workflows", []):
        if "monetag" in w.get("path", "") or "monetag" in w.get("name", "").lower():
            return w
    return data.get("workflows", [None])[0] if data.get("workflows") else None

def get_runs(owner, repo, token, per=5):
    data = gh(f"/repos/{owner}/{repo}/actions/runs?per_page={per}", token)
    if isinstance(data, dict) and data.get("error"):
        return []
    return data.get("workflow_runs", [])

def extract_destination(token, owner, repo, run_id):
    url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(f"{GITHUB_API}{url}")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "monetag-tui/3.0")
    try:
        with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            found_dest_line = False
            for name in zf.namelist():
                if not name.endswith(".txt"):
                    continue
                for line in zf.read(name).decode(errors="replace").split("\n"):
                    s = line.strip()
                    if "DESTINATION URL:" in s or "Destination:" in s:
                        val = s.split(":", 1)[-1].strip()
                        if val.startswith("http"):
                            return val
                        found_dest_line = True
                    elif found_dest_line and s.startswith("http"):
                        return s
                    else:
                        found_dest_line = False
    except Exception:
        pass
    return ""

def get_run_logs(token, owner, repo, run_id):
    url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(f"{GITHUB_API}{url}")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "monetag-tui/3.0")
    try:
        with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            logs = {}
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    logs[name] = zf.read(name).decode(errors="replace")
            return logs
    except Exception:
        return {}

# ─── Deployment Config Recovery ───────────────────────────────────────────────

def parse_run_log_config(logs):
    """Pull a deployment's config from the 'Validate SmartLink URL' log echoes."""
    cfg = {}
    text = "\n".join(logs.values())
    m = re.search(r"SmartLink:\s*(\S+)", text)
    if m and m.group(1).startswith("http"):
        cfg["smartlink_url"] = m.group(1)
    m = re.search(r"Traffic source:\s*(\S+)", text)
    if m:
        cfg["traffic_source"] = m.group(1)
    m = re.search(r"Referrer \(traffic source URL\):\s*(\S+)", text)
    if m and m.group(1):
        cfg["traffic_source_url"] = m.group(1)
    m = re.search(r"Verify mode:\s*(\S+)", text)
    if m:
        cfg["verify_mode"] = m.group(1)
    m = re.search(r"Views:\s*(\S+)", text)
    if m:
        cfg["views"] = m.group(1)
    return cfg

def recover_deployment_config(token, owner, rn):
    """Recover a deployment's current config (SmartLink/traffic) from GitHub."""
    cfg = {}
    runs = get_runs(owner, rn, token, per=3)
    for run in runs:
        inputs = run.get("inputs") or {}
        if inputs.get("smartlink_url"):
            for k in ("smartlink_url", "traffic_source_url", "traffic_source", "verify_mode", "views"):
                if inputs.get(k):
                    cfg[k] = inputs[k]
            return cfg
        if run.get("conclusion") in ("success", "failure", "cancelled"):
            logs = get_run_logs(token, owner, rn, run["id"])
            cfg = parse_run_log_config(logs)
            if cfg.get("smartlink_url"):
                return cfg
    return cfg

# ─── Secret Encryption ────────────────────────────────────────────────────────

def encrypt_secret(public_key_b64, plaintext):
    """Encrypt a secret value using the repo's public key (RSA or NaCl box)."""
    raw = base64.b64decode(public_key_b64)

    # GitHub uses NaCl box (X25519) for newer repos, RSA for older ones
    # Detect by key size: 32 bytes = X25519, larger = RSA
    if len(raw) == 32 and HAS_NACL:
        recipient = nacl.public.PublicKey(raw)
        sealed = nacl.public.SealedBox(recipient)
        encrypted = sealed.encrypt(plaintext.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")
    elif HAS_CRYPTO and len(raw) != 32:
        der = raw
        pub = serialization.load_der_public_key(der)
        encrypted = pub.encrypt(
            plaintext.encode("utf-8"),
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
        return base64.b64encode(encrypted).decode("utf-8")
    else:
        return None

def set_repo_secret(owner, repo, token, secret_name, secret_value):
    """Set a GitHub Actions secret with proper RSA-OAEP encryption."""
    key_data = gh(f"/repos/{owner}/{repo}/actions/secrets/public-key", token)
    if isinstance(key_data, dict) and key_data.get("error"):
        return False, f"Failed to get public key: {key_data.get('message', '')}"

    pub_key = key_data.get("key", "")
    key_id = key_data.get("key_id", "")
    if not pub_key or not key_id:
        return False, "No public key returned"

    encrypted = encrypt_secret(pub_key, secret_value)
    if not encrypted:
        return False, "Encryption failed"

    result = gh(f"/repos/{owner}/{repo}/actions/secrets/{secret_name}", token, "PUT", {
        "encrypted_value": encrypted,
        "key_id": key_id,
    })
    if isinstance(result, dict) and result.get("error"):
        return False, f"Failed to set secret: {result.get('message', '')}"
    return True, None

# ─── Deploy / Remove ──────────────────────────────────────────────────────────

def deploy_new(repo_name, token, username, settings, step_cb=None, smartlink_url="", traffic_source_url=""):
    """Deploy a new Monetag instance. step_cb(step_num, msg) for progress."""
    full_name = repo_name if repo_name.startswith("monetag-") else f"monetag-{repo_name}"
    repo_created = False

    def step(n, msg):
        if step_cb:
            step_cb(n, msg)

    def fail(msg):
        if repo_created:
            _cleanup_repo(username, full_name, token)
        return None, msg

    # Check if repo already exists
    step(1, f"Checking if {full_name} exists...")
    check = gh(f"/repos/{username}/{full_name}", token)
    if not (isinstance(check, dict) and check.get("error")):
        return None, f"Repo {full_name} already exists on @{username}"

    # Create repo
    step(2, f"Creating repo {full_name}...")
    create_resp = gh("/user/repos", token, "POST", {
        "name": full_name, "private": False, "auto_init": True,
        "description": "Monetag SmartLink automation relay",
    })
    if isinstance(create_resp, dict) and create_resp.get("error"):
        return None, f"Create repo failed: {create_resp.get('message', '')}"
    repo_created = True

    # Clone/update template
    step(3, "Cloning template repo...")
    template_dir = str(DATA_DIR / "template")
    template_path = Path(template_dir)
    if template_path.exists():
        # Update if stale
        age = time.time() - template_path.stat().st_mtime
        if age > TEMPLATE_MAX_AGE:
            step(3, "Updating template repo...")
            r = subprocess.run(
                ["git", "-C", template_dir, "pull", "--ff-only", "-q"],
                capture_output=True, timeout=DEPLOY_TIMEOUT,
            )
            if r.returncode != 0:
                # Re-clone on pull failure
                shutil.rmtree(template_dir, ignore_errors=True)
                r = subprocess.run(
                    ["git", "clone", "--depth", "1", f"https://github.com/{TEMPLATE_REPO}.git", template_dir],
                    capture_output=True, timeout=DEPLOY_TIMEOUT,
                )
                if r.returncode != 0:
                    return fail(f"Clone template failed: {r.stderr.decode(errors='replace')}")
    else:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", f"https://github.com/{TEMPLATE_REPO}.git", template_dir],
            capture_output=True, timeout=DEPLOY_TIMEOUT,
        )
        if r.returncode != 0:
            return fail(f"Clone template failed: {r.stderr.decode(errors='replace')}")

    # Copy template to new dir
    step(4, "Copying template files...")
    repo_dir = str(DATA_DIR / "repos" / full_name)
    Path(repo_dir).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rm", "-rf", repo_dir], capture_output=True)
    shutil.copytree(template_dir, repo_dir, ignore=lambda d, files: [".git"] if ".git" in files else [])

    # Push to new repo
    step(5, "Pushing to GitHub...")
    env = os.environ.copy()
    env["GIT_ASKPASS"] = "echo"
    env["GIT_AUTHOR_EMAIL"] = "monetag@deploy"
    env["GIT_AUTHOR_NAME"] = "Monetag Deploy"
    env["GIT_COMMITTER_EMAIL"] = "monetag@deploy"
    env["GIT_COMMITTER_NAME"] = "Monetag Deploy"
    token_url = f"https://{token}@github.com/{username}/{full_name}.git"

    for cmd in [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "monetag@deploy"],
        ["git", "config", "user.name", "Monetag Deploy"],
        ["git", "remote", "add", "origin", token_url],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "init: monetag automation relay"],
        ["git", "push", "--force", "origin", "main"],
    ]:
        r = subprocess.run(cmd, cwd=repo_dir, capture_output=True, timeout=GIT_TIMEOUT, env=env)
        if r.returncode != 0:
            err = (r.stderr or r.stdout).decode(errors="replace").strip().replace(token, "***")
            if cmd[1] == "push":
                return fail(f"Git push failed: {err}")
            elif cmd[1] == "commit" and "nothing to commit" in err:
                pass
            else:
                return fail(f"Git {cmd[1]} failed: {err}")

    # Set secrets with encryption
    step(6, "Setting encrypted secrets...")
    secrets = {
        "RELAY_TARGET_REPO": f"{username}/{full_name}",
        "LOOP_TRIGGER_TOKEN": token,
    }
    if smartlink_url:
        secrets["MONETAG_SMARTLINK_URL"] = smartlink_url
    if traffic_source_url:
        secrets["MONETAG_REFERER"] = traffic_source_url
    su, sk, ss = get_supabase_creds(settings)
    if su:
        secrets["SUPABASE_URL"] = su
    if sk:
        secrets["SUPABASE_KEY"] = sk
    if ss:
        secrets["SUPABASE_SECRET"] = ss
    if not su:
        warn("No Supabase URL found — proxy will not work on deployed repo!")
        warn("Set it in Settings [1] or ~/.config/monetag/config.json")

    secret_errors = []
    for sname, sval in secrets.items():
        ok, err = set_repo_secret(username, full_name, token, sname, sval)
        if not ok:
            secret_errors.append(f"{sname}: {err}")

    if secret_errors:
        return fail(f"Failed to set secrets: {'; '.join(secret_errors)}")

    # Enable + dispatch workflow
    step(7, "Enabling workflow...")
    time.sleep(WORKFLOW_ENABLE_DELAY)
    wf = None
    for _attempt in range(WORKFLOW_ENABLE_RETRIES):
        wf = get_workflow(username, full_name, token)
        if wf:
            break
        time.sleep(WORKFLOW_ENABLE_RETRY_DELAY)
    if wf:
        gh(f"/repos/{username}/{full_name}/actions/workflows/{wf['id']}/enable", token, "PUT")
        step(8, "Dispatching workflow...")
        inputs = {}
        if smartlink_url:
            inputs["smartlink_url"] = smartlink_url
        if traffic_source_url:
            inputs["traffic_source_url"] = traffic_source_url
        gh(f"/repos/{username}/{full_name}/actions/workflows/{wf['id']}/dispatches", token, "POST",
           {"ref": "main", "inputs": inputs})
    else:
        step(8, "Warning: no workflow found to enable")

    # Save deployment locally
    dep = {
        "name": full_name, "account": username,
        "repo_url": f"https://github.com/{username}/{full_name}",
        "status": "deployed", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if smartlink_url:
        dep["smartlink_url"] = smartlink_url
    if traffic_source_url:
        dep["traffic_source_url"] = traffic_source_url
    deps = load_json("deployments.json")
    deps[full_name] = dep
    save_json("deployments.json", deps)
    return dep, None

def _cleanup_repo(owner, name, token):
    """Delete a GitHub repo if it was partially created during deploy."""
    try:
        gh(f"/repos/{owner}/{name}", token, "DELETE")
    except Exception:
        pass
    repo_dir = DATA_DIR / "repos" / name
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)

def remove_deployment(name):
    deps = load_json("deployments.json")
    dep = deps.get(name)
    if not dep:
        return False, "Deployment not found"
    accounts = load_json("accounts.json")
    acct = accounts.get(dep.get("account", ""))
    if acct:
        owner = acct.get("username", dep.get("account", ""))
        resp = gh(f"/repos/{owner}/{name}", acct.get("token", ""), "DELETE")
        if isinstance(resp, dict) and resp.get("error"):
            return False, f"GitHub API error: {resp.get('message', '')}"
    # Clean up local repo directory
    repo_dir = DATA_DIR / "repos" / name
    if repo_dir.exists():
        shutil.rmtree(repo_dir, ignore_errors=True)
    del deps[name]
    save_json("deployments.json", deps)
    return True, None

def nuke_deployments():
    deps = load_json("deployments.json")
    accounts = load_json("accounts.json")
    deleted = 0
    errors = 0
    for name, dep in list(deps.items()):
        acct = accounts.get(dep.get("account", ""))
        if acct:
            owner = acct.get("username", dep.get("account", ""))
            resp = gh(f"/repos/{owner}/{name}", acct.get("token", ""), "DELETE")
            if isinstance(resp, dict) and resp.get("error"):
                errors += 1
            else:
                deleted += 1
        # Clean up local repo directory
        repo_dir = DATA_DIR / "repos" / name
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
    save_json("deployments.json", {})
    return deleted, errors

# ─── UI Helpers ───────────────────────────────────────────────────────────────

def clear():
    subprocess.run(["clear"] if os.name != "nt" else ["cls"], capture_output=True)

def banner():
    print(f"""
{C_CYAN}{C_BOLD}╔══════════════════════════════════════════════════════════╗
║                 M O N E T A G   C O N T R O L             ║
╚══════════════════════════════════════════════════════════╝{C_RESET}""")

def status_line():
    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    active = settings.get("active_account")
    deps = load_json("deployments.json")
    n_acct = len(accounts)
    n_dep = len(deps)
    if active and active in accounts:
        user = accounts[active].get("username", active)
        print(f"  {C_DIM}Account:{C_RESET} {C_GREEN}{user}{C_RESET}  "
              f"{C_DIM}Accounts:{C_RESET} {n_acct}  "
              f"{C_DIM}Deployments:{C_RESET} {n_dep}")
    elif n_acct == 0:
        print(f"  {C_YELLOW}No accounts configured{C_RESET}")
    else:
        print(f"  {C_DIM}Active:{C_RESET} {C_YELLOW}none{C_RESET}  "
              f"{C_DIM}Accounts:{C_RESET} {n_acct}  "
              f"{C_DIM}Deployments:{C_RESET} {n_dep}")

def divider():
    print(f"  {C_DIM}{'─' * 56}{C_RESET}")

def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}▸{C_RESET} {msg}{suffix}: ").strip()
    return val if val else (default or "")

def confirm(msg):
    val = input(f"  {C_YELLOW}?{C_RESET} {msg} (y/N): ").strip().lower()
    return val in ("y", "yes")

def success(msg):
    print(f"  {C_GREEN}✓ {msg}{C_RESET}")

def error(msg):
    print(f"  {C_RED}✗ {msg}{C_RESET}")

def info(msg):
    print(f"  {C_BLUE}ℹ {msg}{C_RESET}")

def warn(msg):
    print(f"  {C_YELLOW}⚠ {msg}{C_RESET}")

def loading(msg):
    print(f"  {C_DIM}⏳ {msg}...{C_RESET}")

def progress(num, total, msg):
    print(f"  {C_BOLD}[{num}/{total}]{C_RESET} {msg}")

def get_active_token():
    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    active = settings.get("active_account")
    if active and active in accounts:
        return accounts[active].get("token", ""), active
    return None, None

def get_account_for_repo(repo_name):
    """Find which local account owns a given deployment."""
    deps = load_json("deployments.json")
    accounts = load_json("accounts.json")
    dep = deps.get(repo_name)
    if dep:
        acct_name = dep.get("account", "")
        acct = accounts.get(acct_name, {})
        return acct_name, acct
    return None, None

# ─── Screen: Accounts ─────────────────────────────────────────────────────────

def screen_accounts():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}ACCOUNTS{C_RESET}")
        divider()
        accounts = load_json("accounts.json")
        settings = load_json("settings.json")
        active = settings.get("active_account")
        accts = list(accounts.values())
        if not accts:
            print(f"\n  {C_DIM}No accounts configured yet.{C_RESET}")
            print(f"  {C_DIM}Add a GitHub account to get started.{C_RESET}\n")
        else:
            deps = load_json("deployments.json")
            for key, a in accounts.items():
                acct_name = a.get("name", key)
                is_active = acct_name == active
                marker = f"{C_GREEN}●{C_RESET}" if is_active else f"{C_DIM}○{C_RESET}"
                user = a.get("username", "?")
                tok = a.get("token", "")
                n_deps = sum(1 for d in deps.values() if d.get("account") == acct_name)
                print(f"  {marker} {C_BOLD}{acct_name}{C_RESET} "
                      f"{C_DIM}@{user}  {tok[:4]}...{tok[-4:]}{C_RESET}  "
                      f"{C_DIM}{n_deps} deployments{C_RESET}")
            print()
        print(f"  {C_BOLD}[1]{C_RESET} Add account")
        print(f"  {C_BOLD}[2]{C_RESET} Remove account")
        if accts:
            print(f"  {C_BOLD}[3]{C_RESET} Switch active")
            print(f"  {C_BOLD}[4]{C_RESET} Validate token")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            name = prompt("Account name (e.g. main)")
            if not name:
                continue
            token = prompt("GitHub Personal Access Token")
            if not token:
                continue
            if name in accounts:
                error("Account name already exists")
                continue
            loading("Validating token")
            user_data = gh_user(token)
            if isinstance(user_data, dict) and user_data.get("login"):
                username = user_data["login"]
                scopes = user_data.get("_scopes", "")
                scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
                accounts[name] = {"name": name, "token": token, "username": username}
                save_json("accounts.json", accounts)
                if not active:
                    settings["active_account"] = name
                    save_json("settings.json", settings)
                success(f"Added @{username}")
                if not any("repo" in s for s in scope_list):
                    warn("Token missing 'repo' scope")
                if not any("workflow" in s for s in scope_list):
                    warn("Token missing 'workflow' scope")
                info("Run Doctor [9] to verify the whole setup.")
                if confirm(f"Import existing monetag deployments from @{username} into the local database now?"):
                    existing = load_json("deployments.json")
                    n, u, e, rec = sync_account(name, accounts[name], existing)
                    save_json("accounts.json", accounts)
                    save_json("deployments.json", existing)
                    print()
                    if n or u:
                        success(f"Imported {len(n)} new + {len(u)} existing deployments")
                        if rec:
                            success(f"Recovered config (SmartLink / traffic) for {rec} deployment(s)")
                            info("Use Trigger / re-dispatch [4] to change a link or traffic.")
                    else:
                        info("No monetag-* repos found for this account")
                    for err in e:
                        warn(err)
            else:
                error("Invalid token")
        elif choice == "2" and accts:
            name = prompt("Account name to remove")
            if name and name in accounts:
                if confirm(f"Remove '{name}'?"):
                    del accounts[name]
                    save_json("accounts.json", accounts)
                    if active == name:
                        settings["active_account"] = None
                        save_json("settings.json", settings)
                    success(f"Removed '{name}'")
            elif name:
                error("Account not found")
        elif choice == "3" and accts:
            name = prompt("Account name to activate")
            if name and name in accounts:
                settings["active_account"] = name
                save_json("settings.json", settings)
                success(f"Activated '{name}'")
            elif name:
                error("Account not found")
        elif choice == "4" and accts:
            name = prompt("Account name to validate")
            if name and name in accounts:
                loading(f"Validating token for '{name}'")
                user_data = gh_user(accounts[name].get("token", ""))
                if isinstance(user_data, dict) and user_data.get("login"):
                    accounts[name]["username"] = user_data["login"]
                    save_json("accounts.json", accounts)
                    scopes = user_data.get("_scopes", "")
                    success(f"@{user_data['login']} — scopes: {scopes or 'none'}")
                else:
                    error(f"Token invalid or expired: {user_data.get('message', '')}")
                input(f"\n  Press Enter to continue...")
            elif name:
                error("Account not found")

# ─── Screen: Deploy ───────────────────────────────────────────────────────────

def screen_deploy():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DEPLOY NEW INSTANCE{C_RESET}")
    divider()

    if not HAS_CRYPTO and not HAS_NACL:
        warn("Neither 'cryptography' nor 'nacl' library installed — secrets cannot be encrypted")
        warn("Install with: pip install cryptography pynacl")
        if not confirm("Continue anyway (secrets won't work)?"):
            return

    token, acct_name = get_active_token()
    if not token:
        error("No active account. Go to Accounts first.")
        input(f"\n  Press Enter to continue...")
        return

    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    username = accounts[acct_name].get("username", acct_name)

    repo_name = prompt("Repo name (will create monetag-{name})")
    if not repo_name:
        return
    if not validate_repo_name(repo_name.replace("monetag-", "", 1)):
        error("Invalid repo name — use only letters, numbers, hyphens, underscores")
        input(f"\n  Press Enter to continue...")
        return
    full_name = repo_name if repo_name.startswith("monetag-") else f"monetag-{repo_name}"
    settings = load_json("settings.json")
    smartlink_url = prompt("Monetag link (SmartLink URL)", settings.get("smartlink_url", ""))
    smartlink_url = normalize_url(smartlink_url)
    if not smartlink_url:
        error("SmartLink URL is required")
        input(f"\n  Press Enter to continue...")
        return
    if not looks_like_url(smartlink_url):
        warn(f"'{smartlink_url}' does not look like a valid URL")
        if not confirm("Continue anyway?"):
            return
    traffic_source_url = prompt("Traffic source URL (YouTube / any link, blank = none)",
                                settings.get("traffic_source_url", ""))
    traffic_source_url = normalize_url(traffic_source_url)

    if not confirm(f"Deploy {full_name} as @{username}?"):
        return

    print()
    TOTAL = 8
    def show_step(n, msg):
        print(f"  {C_BOLD}[{n}/{TOTAL}]{C_RESET} {msg}")

    dep, err = deploy_new(repo_name, token, username, settings, step_cb=show_step,
                          smartlink_url=smartlink_url, traffic_source_url=traffic_source_url)
    print()
    if err:
        error(err)
    else:
        success(f"Deployed: {dep['name']}")
        info(f"Repo: {dep['repo_url']}")
        info("Workflow will run automatically within ~1 minute")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Remove ───────────────────────────────────────────────────────────

def screen_remove():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}REMOVE DEPLOYMENT{C_RESET}")
        divider()
        deps = load_json("deployments.json")
        dep_list = list(deps.values())
        if not dep_list:
            print(f"\n  {C_DIM}No deployments to remove.{C_RESET}\n")
            input(f"  Press Enter to continue...")
            return
        for i, d in enumerate(dep_list, 1):
            dep_status = d.get("status", "?")
            status_color = C_GREEN if dep_status == "success" else C_YELLOW if dep_status == "deployed" else C_RED
            print(f"  {C_BOLD}{i}.{C_RESET} {d['name']}  "
                  f"{status_color}{dep_status}{C_RESET}  "
                  f"{C_DIM}{d.get('account', '?')}{C_RESET}")
        print(f"\n  {C_BOLD}[N]{C_RESET} Remove deployment N")
        print(f"  {C_BOLD}[a]{C_RESET} Nuke ALL deployments")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "a":
            if confirm(f"DELETE ALL {len(dep_list)} DEPLOYMENTS? This removes GitHub repos too!"):
                loading("Nuking all deployments")
                deleted, errors = nuke_deployments()
                if errors:
                    warn(f"Nuked {deleted} deployments ({errors} failed)")
                else:
                    success(f"Nuked {deleted} deployments")
                input(f"\n  Press Enter to continue...")
                return
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(dep_list):
                d = dep_list[idx]
                if confirm(f"Remove '{d['name']}'? (deletes GitHub repo)"):
                    loading(f"Removing {d['name']}")
                    ok, err = remove_deployment(d["name"])
                    if ok:
                        success(f"Removed {d['name']}")
                    else:
                        error(err)
                    input(f"\n  Press Enter to continue...")

# ─── Screen: Status ───────────────────────────────────────────────────────────

def screen_status():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DEPLOYMENT STATUS{C_RESET}")
    divider()

    token, _ = get_active_token()
    if not token:
        error("No active account")
        input(f"\n  Press Enter to continue...")
        return

    loading("Fetching deployments from GitHub")
    repos = get_monetag_repos(token)
    if isinstance(repos, dict) and repos.get("_rate_limited"):
        error("Rate-limited by GitHub API. Try again later.")
        input(f"\n  Press Enter to continue...")
        return
    if not repos:
        print(f"\n  {C_DIM}No monetag-* repos found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    cache = load_json("status_cache.json")
    print()
    for repo in repos:
        rn = repo["name"]
        owner = repo["owner"]["login"]
        c = cache.get(rn, {})
        dest = c.get("destination", "")
        consec_fails = c.get("consecutive_fails", 0)
        total_ok = c.get("total_successes", 0)

        runs = get_runs(owner, rn, token, per=1)
        if runs:
            latest = runs[0]
            status = latest.get("conclusion") or latest.get("status", "unknown")
            created = latest.get("created_at", "")[:16].replace("T", " ")
        else:
            status = "no_runs"
            created = "never"

        sc = C_GREEN if status == "success" else C_RED if status == "failure" else C_YELLOW
        print(f"  {C_BOLD}{rn}{C_RESET}  {C_DIM}(@{owner}){C_RESET}")
        print(f"    {C_DIM}Status:{C_RESET} {sc}{status}{C_RESET}  "
              f"{C_DIM}Last:{C_RESET} {created}  "
              f"{C_DIM}OK:{C_RESET} {total_ok}  "
              f"{C_DIM}Fails:{C_RESET} {consec_fails}")
        if dest:
            print(f"    {C_DIM}Destination:{C_RESET} {C_BRGREEN}{dest}{C_RESET}")
        print()

    input(f"  Press Enter to continue...")

# ─── Screen: Logs ─────────────────────────────────────────────────────────────

def screen_logs():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}VIEW WORKFLOW LOGS{C_RESET}")
    divider()

    token, _ = get_active_token()
    if not token:
        error("No active account")
        input(f"\n  Press Enter to continue...")
        return

    repos = get_monetag_repos(token)
    if isinstance(repos, dict) and repos.get("_rate_limited"):
        error("Rate-limited by GitHub API. Try again later.")
        input(f"\n  Press Enter to continue...")
        return
    if not repos:
        print(f"\n  {C_DIM}No monetag-* repos found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    print()
    for i, repo in enumerate(repos, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {repo['name']}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice = prompt("Select repo")
    if not choice or choice == "0" or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(repos):
        return

    repo = repos[idx]
    owner = repo["owner"]["login"]
    rn = repo["name"]

    loading(f"Fetching runs for {rn}")
    runs = get_runs(owner, rn, token, per=10)
    if not runs:
        print(f"\n  {C_DIM}No workflow runs found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    print()
    print(f"  {C_BOLD}Recent runs for {rn}:{C_RESET}")
    print()
    for i, run in enumerate(runs, 1):
        sc = C_GREEN if run.get("conclusion") == "success" else C_RED if run.get("conclusion") == "failure" else C_YELLOW
        created = run.get("created_at", "")[:16].replace("T", " ")
        print(f"  {C_BOLD}{i:2d}.{C_RESET} #{run['number']:4d}  "
              f"{sc}{run.get('conclusion', run['status']):10s}{C_RESET}  {created}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice2 = prompt("Select run")
    if not choice2 or choice2 == "0" or not choice2.isdigit():
        return

    idx2 = int(choice2) - 1
    if idx2 < 0 or idx2 >= len(runs):
        return

    run = runs[idx2]
    print()
    loading(f"Fetching logs for run #{run['number']}")

    dest = extract_destination(token, owner, rn, run["id"])
    if dest:
        success(f"Destination: {dest}")
    else:
        info("No destination found in this run")

    logs = get_run_logs(token, owner, rn, run["id"])
    if not logs:
        print(f"\n  {C_DIM}No logs available.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    for name, content in logs.items():
        print(f"\n  {C_CYAN}{'─' * 56}{C_RESET}")
        print(f"  {C_BOLD}{name}{C_RESET}")
        print(f"  {C_CYAN}{'─' * 56}{C_RESET}")
        lines = content.split("\n")
        for line in lines[-LOG_MAX_LINES:]:
            print(f"  {C_DIM}{line}{C_RESET}")
        if len(lines) > LOG_MAX_LINES:
            print(f"  {C_DIM}... ({len(lines) - 80} lines hidden){C_RESET}")

    input(f"\n  Press Enter to continue...")

# ─── Screen: Sync ─────────────────────────────────────────────────────────────

def sync_account(name, acct, existing):
    """Scan one account's monetag-* repos and merge them into the local database.
    Returns (new_repos, updated_repos, errors, recovered_count)."""
    new_repos, updated_repos, errors, recovered = [], [], [], 0
    tok = acct.get("token", "")
    if not tok:
        errors.append(f"@{name}: no token")
        return new_repos, updated_repos, errors, recovered
    loading(f"Scanning @{acct.get('username', name)}")
    try:
        repos = paginate_repos(tok)
        if isinstance(repos, dict) and repos.get("_rate_limited"):
            errors.append(f"@{name}: rate-limited by GitHub API")
            return new_repos, updated_repos, errors, recovered
        monetag = [r for r in repos if r["name"].startswith("monetag-")]
        owner = monetag[0]["owner"]["login"] if monetag else acct.get("username", name)
        acct["username"] = owner
        for repo in monetag:
            rn = repo["name"]
            status = "unknown"
            dest = ""
            cfg = {}
            try:
                runs = get_runs(owner, rn, tok, per=3)
                last = runs[0] if runs else None
                status = (last.get("conclusion") or last.get("status", "unknown")) if last else "no_runs"
                if last and last.get("conclusion") == "success":
                    dest = extract_destination(tok, owner, rn, last["id"])
                cfg = recover_deployment_config(tok, owner, rn)
                if cfg:
                    recovered += 1
            except Exception as e:
                status = "unknown"
                errors.append(f"{rn}: {str(e)[:40]}")

            if rn in existing:
                existing[rn]["status"] = status
                existing[rn]["account"] = name
                if dest:
                    existing[rn]["destination"] = dest
                for k, v in cfg.items():
                    if v:
                        existing[rn][k] = v
                updated_repos.append(rn)
            else:
                rec = {
                    "name": rn, "account": name,
                    "repo_url": repo["html_url"], "status": status,
                    "destination": dest,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                rec.update({k: v for k, v in cfg.items() if v})
                existing[rn] = rec
                new_repos.append(rn)
    except Exception as e:
        errors.append(f"@{name}: {str(e)[:40]}")
    return new_repos, updated_repos, errors, recovered

def screen_sync():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}SYNC FROM GITHUB{C_RESET}")
    divider()
    info("Imports existing monetag-* deployments into the local database.")
    info("Recovers each deployment's SmartLink + traffic config from run logs,")
    info("so you can re-dispatch them from a new device.")

    accounts = load_json("accounts.json")
    if not accounts:
        error("No accounts configured")
        input(f"\n  Press Enter to continue...")
        return

    existing = load_json("deployments.json")
    new_repos = []
    updated_repos = []
    errors = []
    recovered_total = 0

    for name, acct in accounts.items():
        n, u, e, rec = sync_account(name, acct, existing)
        new_repos += n
        updated_repos += u
        errors += e
        recovered_total += rec

    save_json("accounts.json", accounts)
    save_json("deployments.json", existing)

    print()
    if new_repos or updated_repos:
        success("Sync complete")
    else:
        info("Nothing new found")
    print(f"  {C_DIM}New:{C_RESET} {len(new_repos)}  "
          f"{C_DIM}Updated:{C_RESET} {len(updated_repos)}  "
          f"{C_DIM}Total:{C_RESET} {len(existing)}")
    if new_repos:
        print(f"  {C_GREEN}New repos:{C_RESET} {', '.join(new_repos)}")
    if recovered_total:
        success(f"Recovered config (SmartLink / traffic) for {recovered_total} deployment(s)")
        info("Use Trigger / re-dispatch [4] to pick a deployment and change the link or traffic.")
    if errors:
        for e in errors:
            warn(e)
    input(f"\n  Press Enter to continue...")

# ─── Screen: Dispatch / Re-dispatch ───────────────────────────────────────────

def screen_dispatch():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}TRIGGER / RE-DISPATCH WORKFLOW{C_RESET}")
    divider()
    info("Change the Monetag link or traffic source URL and re-trigger.")
    info("Defaults come from Settings [8]; values are saved for next time.")

    token, _ = get_active_token()
    if not token:
        error("No active account")
        input(f"\n  Press Enter to continue...")
        return

    repos = get_monetag_repos(token)
    if not repos:
        print(f"\n  {C_DIM}No monetag-* repos found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    print()
    for i, repo in enumerate(repos, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {repo['name']}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice = prompt("Select repo to trigger")
    if not choice or choice == "0" or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(repos):
        return

    repo = repos[idx]
    owner = repo["owner"]["login"]
    rn = repo["name"]
    settings = load_json("settings.json")
    deps = load_json("deployments.json")
    dep = deps.get(rn, {})

    info(f"Deployment: {rn} (@{owner})")
    if dep.get("smartlink_url"):
        info(f"Current link: {dep['smartlink_url']}")
    if dep.get("traffic_source_url"):
        info(f"Current referrer: {dep['traffic_source_url']}")
    if dep.get("traffic_source"):
        info(f"Current source: {dep['traffic_source']}")
    if not dep.get("smartlink_url"):
        loading(f"Recovering config for {rn} from GitHub")
        cfg = recover_deployment_config(token, owner, rn)
        if cfg.get("smartlink_url"):
            dep.update({k: v for k, v in cfg.items() if v})
            deps[rn] = dep
            save_json("deployments.json", deps)
            success("Recovered deployment config (SmartLink / traffic) from GitHub")
        else:
            info("No previous run found — defaults come from Settings [8]")
    print()

    def_or_sl = dep.get("smartlink_url") or settings.get("smartlink_url") or ""
    def_or_ts = dep.get("traffic_source_url") or settings.get("traffic_source_url") or ""
    def_or_src = dep.get("traffic_source") or settings.get("traffic_source") or "youtube"

    smartlink_url = prompt("Monetag link (SmartLink URL)", def_or_sl)
    traffic_source_url = prompt("Traffic source URL (YouTube / any link, blank = none)", def_or_ts)
    traffic_source = prompt("Traffic source (youtube|google|facebook|twitter|direct)", def_or_src)

    smartlink_url = normalize_url(smartlink_url)
    traffic_source_url = normalize_url(traffic_source_url)

    valid_sources = ("youtube", "google", "facebook", "twitter", "direct")
    if traffic_source and traffic_source not in valid_sources:
        warn(f"'{traffic_source}' is not a valid traffic source — using 'youtube' instead")
        traffic_source = "youtube"

    if smartlink_url and not looks_like_url(smartlink_url):
        warn(f"'{smartlink_url}' does not look like a valid URL")
        if not confirm("Continue anyway?"):
            return
    if not smartlink_url:
        warn("No SmartLink URL set — the workflow may not produce views")
        if not confirm("Continue without a SmartLink URL?"):
            return

    inputs = {}
    if smartlink_url:
        inputs["smartlink_url"] = smartlink_url
    if traffic_source_url:
        inputs["traffic_source_url"] = traffic_source_url
    if traffic_source:
        inputs["traffic_source"] = traffic_source

    if not confirm(f"Trigger workflow on {rn}?\n"
                   f"  SmartLink: {smartlink_url or '(none)'}\n"
                   f"  Traffic source URL: {traffic_source_url or '(none)'}\n"
                   f"  Traffic source: {traffic_source or '(default)'}"):
        return

    loading(f"Dispatching workflow on {rn}")
    wf = get_workflow(owner, rn, token)
    if not wf:
        error("No workflow found")
        input(f"\n  Press Enter to continue...")
        return

    resp = gh(f"/repos/{owner}/{rn}/actions/workflows/{wf['id']}/dispatches", token, "POST",
              {"ref": "main", "inputs": inputs})
    if isinstance(resp, dict) and resp.get("error"):
        error(f"Dispatch failed: {resp.get('message', '')}")
    else:
        success(f"Workflow triggered on {rn}")
        # Persist the URLs so a later re-dispatch keeps using them
        if smartlink_url:
            settings["smartlink_url"] = smartlink_url
            dep["smartlink_url"] = smartlink_url
        if traffic_source_url:
            settings["traffic_source_url"] = traffic_source_url
            dep["traffic_source_url"] = traffic_source_url
        if traffic_source:
            settings["traffic_source"] = traffic_source
            dep["traffic_source"] = traffic_source
        dep["last_dispatch_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        save_json("settings.json", settings)
        save_json("deployments.json", deps)
    input(f"\n  Press Enter to continue...")

# ─── Screen: Settings ─────────────────────────────────────────────────────────

def screen_settings():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}SETTINGS{C_RESET}")
        divider()
        settings = load_json("settings.json")
        su = settings.get("supabase_url", "")
        sk = settings.get("supabase_key", "")
        ss = settings.get("supabase_secret", "")
        sl = settings.get("smartlink_url", "")
        ts_url = settings.get("traffic_source_url", "")

        print(f"  {C_DIM}Supabase URL:{C_RESET}        {su or f'{C_YELLOW}not set{C_RESET}'}")
        print(f"  {C_DIM}Supabase Key:{C_RESET}        {sk[:4]}...{sk[-4:] if len(sk) > 4 else ''}" if sk else f"  {C_DIM}Supabase Key:{C_RESET}        {C_YELLOW}not set{C_RESET}")
        print(f"  {C_DIM}Supabase Secret:{C_RESET}      {ss[:4]}...{ss[-4:] if len(ss) > 4 else ''}" if ss else f"  {C_DIM}Supabase Secret:{C_RESET}      {C_YELLOW}not set{C_RESET}")
        print(f"  {C_DIM}Monetag Link:{C_RESET}          {sl or f'{C_YELLOW}not set{C_RESET}'}")
        print(f"  {C_DIM}Traffic Src URL:{C_RESET}       {ts_url or f'{C_YELLOW}not set{C_RESET}'}")
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Set Supabase URL")
        print(f"  {C_BOLD}[2]{C_RESET} Set Supabase Key")
        print(f"  {C_BOLD}[3]{C_RESET} Set Supabase Secret")
        print(f"  {C_BOLD}[4]{C_RESET} Set Monetag link (SmartLink URL)")
        print(f"  {C_BOLD}[5]{C_RESET} Set Traffic Source URL (YouTube / any link)")
        print(f"  {C_BOLD}[6]{C_RESET} Clear all settings")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            val = prompt("Supabase URL", settings.get("supabase_url"))
            val = normalize_url(val)
            settings["supabase_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "2":
            val = prompt("Supabase Key", settings.get("supabase_key"))
            settings["supabase_key"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "3":
            val = prompt("Supabase Secret", settings.get("supabase_secret"))
            settings["supabase_secret"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "4":
            val = prompt("Monetag link (SmartLink URL)", settings.get("smartlink_url"))
            val = normalize_url(val)
            if val and not looks_like_url(val):
                warn(f"'{val}' does not look like a valid URL — saved anyway")
            settings["smartlink_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "5":
            val = prompt("Traffic source URL (YouTube video / any link)", settings.get("traffic_source_url"))
            val = normalize_url(val)
            if val and not looks_like_url(val):
                warn(f"'{val}' does not look like a valid URL — saved anyway")
            settings["traffic_source_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "6":
            if confirm("Clear all settings?"):
                save_json("settings.json", {})
                success("Settings cleared")

# ─── Doctor / Diagnostics ─────────────────────────────────────────────────────

def _check_import(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False

def _which(bin_name):
    return shutil.which(bin_name)

def _try_pip_install(pkg):
    loading(f"Installing {pkg} (pip)")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--user", pkg],
            capture_output=True, timeout=180,
        )
        return r.returncode == 0
    except Exception:
        return False

def _try_apt_install(pkg):
    loading(f"Installing {pkg} (apt, needs sudo)")
    try:
        r = subprocess.run(
            ["sudo", "apt-get", "install", "-y", pkg],
            capture_output=True, timeout=300,
        )
        return r.returncode == 0
    except Exception:
        return False

def _doc(status, label, detail=""):
    if status == "ok":
        icon, color = f"{C_GREEN}✓{C_RESET}", C_GREEN
    elif status == "warn":
        icon, color = f"{C_YELLOW}⚠{C_RESET}", C_YELLOW
    elif status == "error":
        icon, color = f"{C_RED}✗{C_RESET}", C_RED
    else:
        icon, color = f"{C_BLUE}ℹ{C_RESET}", C_BLUE
    line = f"  {icon} {C_BOLD}{label}{C_RESET}"
    if detail:
        line += f"  {C_DIM}{detail}{C_RESET}"
    print(line)
    return status

def _test_supabase(su, sk):
    """Return (ok:bool, detail:str) for Supabase REST connectivity."""
    if not su or not sk:
        return None, "credentials missing"
    try:
        req = urllib.request.Request(
            f"{su.rstrip('/')}/rest/v1/proxy_results?select=count",
            headers={
                "apikey": sk,
                "Authorization": f"Bearer {sk}",
                "Accept": "application/vnd.pgrst.object+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode()
            return True, f"reachable — proxy_results count {data}"
    except Exception as e:
        return False, f"connection failed ({str(e)[:60]})"

def _doc_check_scopes(scopes):
    missing = []
    if not any("repo" in s for s in scopes):
        missing.append("repo")
    if not any("workflow" in s for s in scopes):
        missing.append("workflow")
    return missing

def _classify_failure(token, owner, rn, run):
    """Inspect a failed run's logs and return (status, guidance)."""
    try:
        logs = get_run_logs(token, owner, rn, run["id"])
        text = "\n".join(logs.values())
    except Exception:
        return "warn", "Could not read logs — check manually in View Logs [6]."

    verdicts = re.findall(r"(VIEW_(?:VERIFIED|LIKELY|WEAK|BLOCKED|INVALID))", text)
    if any(v in ("VIEW_BLOCKED", "VIEW_INVALID") for v in verdicts):
        return ("warn",
                "views were blocked/invalid — SmartLink likely served a Cloudflare challenge "
                "or the traffic looks bot-like. Try a traffic source URL / fresh proxy pool.")
    if "VIEW_WEAK" in verdicts:
        return ("warn",
                "views scored WEAK — set a traffic source URL (referrer) in Settings [8] to "
                "boost the verification score.")
    if re.search(r"ModuleNotFoundError|ImportError:|pip install", text):
        return ("error", "workflow runner is missing a dependency — update the template repo.")
    if re.search(r"Secret|MONETAG_SMARTLINK_URL|SUPABASE_URL|not set", text):
        return ("warn", "workflow is missing secrets — re-deploy or re-set secrets.")
    if re.search(r"exit.?code:?\s+2\b", text, re.I):
        return ("warn", "run exited 2 (blocked/invalid views) — see verdict lines in logs.")
    if re.search(r"rate.?limit|403\b|Unauthorized", text, re.I):
        return ("warn", "GitHub rate limit or auth problem — check the token in Accounts [1].")
    return ("info", "check the full log tail in View Logs [6].")

def screen_doctor():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DOCTOR — DIAGNOSE & AUTO-FIX{C_RESET}")
    divider()
    print(f"  {C_DIM}Checks your whole setup, flags problems, and auto-fixes minor mistakes.{C_RESET}")

    settings = load_json("settings.json")
    deps = load_json("deployments.json")
    accounts = load_json("accounts.json")
    fixes_applied = []
    n_ok = n_warn = n_err = 0

    # ── 1. Local environment ────────────────────────────────────────────────
    print(f"\n  {C_BOLD}1) LOCAL ENVIRONMENT{C_RESET}")
    divider()

    py_ok = sys.version_info >= (3, 8)
    if py_ok:
        n_ok += 1
        _doc("ok", "Python 3.8+", f"Python {sys.version.split()[0]}")
    else:
        n_err += 1
        _doc("error", "Python 3.8+", "too old — upgrade Python")

    if _check_import("selenium"):
        n_ok += 1
        _doc("ok", "selenium", "python library present")
    else:
        n_warn += 1
        _doc("warn", "selenium", "python library missing")
        if confirm("Install 'selenium' now? (auto-fix)"):
            fixes_applied.append("selenium install" if _try_pip_install("selenium") else "selenium (failed)")
            _doc("ok" if _check_import("selenium") else "error", "selenium",
                 "installed" if _check_import("selenium") else "install failed")

    crypto_ok = HAS_CRYPTO or HAS_NACL
    if crypto_ok:
        n_ok += 1
        _doc("ok", "crypto libs", "cryptography/pynacl present")
    else:
        n_warn += 1
        _doc("warn", "crypto libs", "needed to encrypt GitHub secrets")
        if confirm("Install 'cryptography pynacl' now? (auto-fix)"):
            if _try_pip_install("cryptography pynacl"):
                fixes_applied.append("crypto libs")
                _doc("ok", "crypto libs", "installed")
            else:
                _doc("error", "crypto libs", "install failed")

    chrome = _which("chromium") or _which("google-chrome") or _which("chromium-browser")
    if chrome:
        n_ok += 1
        _doc("ok", "Chrome/Chromium", chrome)
    else:
        n_warn += 1
        _doc("warn", "Chrome/Chromium", "no browser found (needed for local runs)")
        if confirm("Install 'chromium' via apt? (auto-fix)"):
            if _try_apt_install("chromium"):
                fixes_applied.append("chromium")
                _doc("ok", "Chrome/Chromium", "installed")
            else:
                _doc("error", "Chrome/Chromium", "install failed")

    cdr = _which("chromedriver") or _which("chromium-driver")
    if cdr:
        n_ok += 1
        _doc("ok", "ChromeDriver", cdr)
    else:
        n_warn += 1
        _doc("warn", "ChromeDriver", "no chromedriver found (needed for local runs)")
        if confirm("Install 'chromedriver' via apt? (auto-fix)"):
            if _try_apt_install("chromedriver"):
                fixes_applied.append("chromedriver")
                _doc("ok", "ChromeDriver", "installed")
            else:
                _doc("error", "ChromeDriver", "install failed")

    # ── 2. Accounts & token ─────────────────────────────────────────────────
    print(f"\n  {C_BOLD}2) GITHUB ACCOUNT{C_RESET}")
    divider()
    if not accounts:
        n_err += 1
        _doc("error", "No accounts", "add one in Accounts [1] first")
    else:
        token, acct_name = get_active_token()
        if not token:
            n_err += 1
            _doc("error", "No active account", "activate one in Accounts [1]")
        else:
            user_data = gh_user(token)
            if isinstance(user_data, dict) and user_data.get("login"):
                n_ok += 1
                _doc("ok", f"Token valid (@{user_data['login']})",
                     f"scopes: {user_data.get('_scopes', '') or 'none'}")
                scopes = [s.strip() for s in user_data.get("_scopes", "").split(",") if s.strip()]
                missing = _doc_check_scopes(scopes)
                if missing:
                    n_warn += 1
                    _doc("warn", "Token scopes",
                         f"missing {', '.join(missing)} — regenerate the token with those scopes checked")
            else:
                n_err += 1
                _doc("error", "Token invalid/expired",
                     f"{user_data.get('message', '')} — fix in Accounts [1]")

    # ── 3. Supabase ─────────────────────────────────────────────────────────
    print(f"\n  {C_BOLD}3) SUPABASE PROXY POOL{C_RESET}")
    divider()
    su, sk, ss = get_supabase_creds(settings)
    if not su or not sk:
        n_err += 1
        _doc("error", "Credentials missing", "needed for the proxy pool")
        if confirm("Fill them in now? (auto-fix)"):
            settings["supabase_url"] = prompt("Supabase URL", su)
            settings["supabase_key"] = prompt("Supabase Key", sk)
            settings["supabase_secret"] = prompt("Supabase Secret", ss)
            save_json("settings.json", settings)
            fixes_applied.append("Supabase credentials")
            su, sk, ss = get_supabase_creds(settings)
            n_err -= 1
    if su and sk:
        ok, detail = _test_supabase(su, sk)
        if ok:
            n_ok += 1
            _doc("ok", "Supabase", detail)
        else:
            n_warn += 1
            _doc("warn", "Supabase", detail)

    # ── 4. Monetag SmartLink ────────────────────────────────────────────────
    print(f"\n  {C_BOLD}4) MONETAG SMARTLINK{C_RESET}")
    divider()
    sl = settings.get("smartlink_url") or ""
    if not sl:
        for d in deps.values():
            if d.get("smartlink_url"):
                sl = d["smartlink_url"]
                break
    if not sl:
        n_err += 1
        _doc("error", "No Monetag link", "SmartLink URL is required to run views")
        if confirm("Set it now? (auto-fix)"):
            val = prompt("Monetag link (SmartLink URL)")
            if val:
                settings["smartlink_url"] = normalize_url(val)
                save_json("settings.json", settings)
                fixes_applied.append("Monetag link")
                sl = settings["smartlink_url"]
                n_err -= 1
    if sl:
        fixed = normalize_url(sl)
        if fixed != sl:
            settings["smartlink_url"] = fixed
            save_json("settings.json", settings)
            fixes_applied.append("SmartLink URL scheme (added https://)")
        if looks_like_url(fixed):
            n_ok += 1
            _doc("ok", "Monetag link", fixed)
        else:
            n_warn += 1
            _doc("warn", "Monetag link", f"'{fixed}' does not look like a valid URL")

    # ── 5. Traffic source ───────────────────────────────────────────────────
    print(f"\n  {C_BOLD}5) TRAFFIC SOURCE{C_RESET}")
    divider()
    ts = settings.get("traffic_source_url", "")
    if ts:
        fixed = normalize_url(ts)
        if fixed != ts:
            settings["traffic_source_url"] = fixed
            save_json("settings.json", settings)
            fixes_applied.append("Traffic source URL scheme (added https://)")
        n_ok += 1
        _doc("ok", "Traffic source URL", fixed)
    else:
        n_ok += 1
        _doc("ok", "Traffic source", "default (youtube); optional custom referrer boosts score")

    # ── 6. Deployments ──────────────────────────────────────────────────────
    print(f"\n  {C_BOLD}6) DEPLOYMENTS{C_RESET}")
    divider()
    if not deps:
        n_ok += 1
        _doc("info", "No deployments yet", "deploy one from Deploy [2]")
    else:
        token, _ = get_active_token()
        for name, dep in deps.items():
            acct_name = dep.get("account", "")
            acct = accounts.get(acct_name, {})
            tok = token or acct.get("token", "")
            owner = acct.get("username", acct_name)
            if not tok or not owner:
                n_warn += 1
                _doc("warn", name, "no token for this deployment's account")
                continue
            runs = get_runs(owner, name, tok, per=1)
            if not runs:
                n_warn += 1
                _doc("warn", name, "no workflow runs yet — wait a minute after dispatch")
                continue
            run = runs[0]
            conclusion = run.get("conclusion") or run.get("status", "unknown")
            if conclusion == "success":
                n_ok += 1
                _doc("ok", name, f"latest run #{run['number']} succeeded")
            elif conclusion in ("failure", "timed_out", "cancelled"):
                n_warn += 1
                st, guide = _classify_failure(tok, owner, name, run)
                _doc(st, name, f"latest run #{run['number']} {conclusion}")
                print(f"        {C_DIM}→ {guide}{C_RESET}")
            else:
                n_warn += 1
                _doc("warn", name, f"latest run #{run['number']} {conclusion}")

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    divider()
    summary = f"  {C_GREEN}{n_ok} OK{C_RESET}"
    if n_warn:
        summary += f"   {C_YELLOW}{n_warn} WARNING{'' if n_warn == 1 else 'S'}{C_RESET}"
    else:
        summary += f"   {C_DIM}0 warnings{C_RESET}"
    if n_err:
        summary += f"   {C_RED}{n_err} ERROR{'' if n_err == 1 else 'S'}{C_RESET}"
    else:
        summary += f"   {C_DIM}0 errors{C_RESET}"
    print(summary)
    if fixes_applied:
        print(f"  {C_GREEN}Auto-fixed:{C_RESET} {', '.join(fixes_applied)}")
    if n_ok and not n_warn and not n_err:
        print(f"  {C_GREEN}All systems go. Nothing to fix.{C_RESET}")
    elif n_err:
        print(f"  {C_DIM}Resolve the errors first, then re-run the doctor.{C_RESET}")
    print()
    input(f"  Press Enter to continue...")

# ─── Main Menu ────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        clear()
        banner()
        status_line()
        print()
        print(f"\n  {C_BOLDWHITE}── MANAGE ──────────────────────{C_RESET}")
        print(f"  {C_BOLD}[1]{C_RESET} Accounts")
        print(f"  {C_BOLD}[2]{C_RESET} Deploy new instance")
        print(f"  {C_BOLD}[3]{C_RESET} Remove deployment")
        print(f"\n  {C_BOLDWHITE}── RUN & MONITOR ────────────────{C_RESET}")
        print(f"  {C_BOLD}[4]{C_RESET} Trigger / re-dispatch workflow (change URLs)")
        print(f"  {C_BOLD}[5]{C_RESET} View status")
        print(f"  {C_BOLD}[6]{C_RESET} View logs")
        print(f"  {C_BOLD}[7]{C_RESET} Sync from GitHub")
        print(f"\n  {C_BOLDWHITE}── CONFIGURE & HEALTH ───────────{C_RESET}")
        print(f"  {C_BOLD}[8]{C_RESET} Settings (URLs, credentials)")
        print(f"  {C_BOLD}[9]{C_RESET} Doctor — diagnose & auto-fix")
        print(f"  {C_BOLD}[0]{C_RESET} Quit\n")

        choice = prompt("Choice")
        if choice == "0" or choice.lower() == "q":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            break
        elif choice == "1":
            screen_accounts()
        elif choice == "2":
            screen_deploy()
        elif choice == "3":
            screen_remove()
        elif choice == "4":
            screen_dispatch()
        elif choice == "5":
            screen_status()
        elif choice == "6":
            screen_logs()
        elif choice == "7":
            screen_sync()
        elif choice == "8":
            screen_settings()
        elif choice == "9":
            screen_doctor()

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for f in ["accounts.json", "deployments.json", "settings.json"]:
        p = DATA_DIR / f
        if not p.exists():
            p.write_text("{}")
    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {C_DIM}Bye!{C_RESET}\n")
        sys.exit(0)
