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
    if not smartlink_url:
        error("SmartLink URL is required")
        input(f"\n  Press Enter to continue...")
        return
    traffic_source_url = prompt("Traffic source URL (YouTube / any link, blank = none)",
                                settings.get("traffic_source_url", ""))
    if traffic_source_url and not traffic_source_url.startswith("http"):
        traffic_source_url = "https://" + traffic_source_url

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

def screen_sync():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}SYNC FROM GITHUB{C_RESET}")
    divider()

    accounts = load_json("accounts.json")
    if not accounts:
        error("No accounts configured")
        input(f"\n  Press Enter to continue...")
        return

    existing = load_json("deployments.json")
    new_repos = []
    updated_repos = []
    errors = []

    for name, acct in accounts.items():
        tok = acct.get("token", "")
        if not tok:
            errors.append(f"@{name}: no token")
            continue
        loading(f"Scanning @{acct.get('username', name)}")
        try:
            repos = paginate_repos(tok)
            if isinstance(repos, dict) and repos.get("_rate_limited"):
                errors.append(f"@{name}: rate-limited by GitHub API")
                continue
            monetag = [r for r in repos if r["name"].startswith("monetag-")]
            owner = monetag[0]["owner"]["login"] if monetag else acct.get("username", name)
            acct["username"] = owner
            for repo in monetag:
                rn = repo["name"]
                status = "unknown"
                dest = ""
                try:
                    runs = get_runs(owner, rn, tok, per=1)
                    last = runs[0] if runs else None
                    status = (last.get("conclusion") or last.get("status", "unknown")) if last else "no_runs"

                    dest = ""
                    if last and last.get("conclusion") == "success":
                        dest = extract_destination(tok, owner, rn, last["id"])
                except Exception as e:
                    status = "unknown"
                    errors.append(f"{rn}: {str(e)[:40]}")

                if rn in existing:
                    existing[rn]["status"] = status
                    existing[rn]["account"] = name
                    if dest:
                        existing[rn]["destination"] = dest
                    updated_repos.append(rn)
                else:
                    existing[rn] = {
                        "name": rn, "account": name,
                        "repo_url": repo["html_url"], "status": status,
                        "destination": dest,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                    new_repos.append(rn)
        except Exception as e:
            errors.append(f"@{name}: {str(e)[:40]}")

    save_json("accounts.json", accounts)
    save_json("deployments.json", existing)

    print()
    if new_repos or updated_repos:
        success(f"Sync complete")
    else:
        info("Nothing new found")
    print(f"  {C_DIM}New:{C_RESET} {len(new_repos)}  "
          f"{C_DIM}Updated:{C_RESET} {len(updated_repos)}  "
          f"{C_DIM}Total:{C_RESET} {len(existing)}")
    if new_repos:
        print(f"  {C_GREEN}New repos:{C_RESET} {', '.join(new_repos)}")
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

    def_or_sl = settings.get("smartlink_url") or dep.get("smartlink_url") or ""
    def_or_ts = settings.get("traffic_source_url") or dep.get("traffic_source_url") or ""
    def_or_src = dep.get("traffic_source") or settings.get("traffic_source") or "youtube"

    smartlink_url = prompt("Monetag link (SmartLink URL)", def_or_sl)
    traffic_source_url = prompt("Traffic source URL (YouTube / any link, blank = none)", def_or_ts)
    traffic_source = prompt("Traffic source (youtube|google|facebook|twitter|direct)", def_or_src)

    if smartlink_url and not smartlink_url.startswith("http"):
        smartlink_url = "https://" + smartlink_url
    if traffic_source_url and not traffic_source_url.startswith("http"):
        traffic_source_url = "https://" + traffic_source_url

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
            settings["smartlink_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "5":
            val = prompt("Traffic source URL (YouTube video / any link)", settings.get("traffic_source_url"))
            settings["traffic_source_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "6":
            if confirm("Clear all settings?"):
                save_json("settings.json", {})
                success("Settings cleared")

# ─── Main Menu ────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        clear()
        banner()
        status_line()
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Accounts")
        print(f"  {C_BOLD}[2]{C_RESET} Deploy new instance")
        print(f"  {C_BOLD}[3]{C_RESET} Remove deployment")
        print(f"  {C_BOLD}[4]{C_RESET} Sync from GitHub")
        print(f"  {C_BOLD}[5]{C_RESET} View status")
        print(f"  {C_BOLD}[6]{C_RESET} View logs")
        print(f"  {C_BOLD}[7]{C_RESET} Trigger / re-dispatch workflow (change URLs)")
        print(f"  {C_BOLD}[8]{C_RESET} Settings")
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
            screen_sync()
        elif choice == "5":
            screen_status()
        elif choice == "6":
            screen_logs()
        elif choice == "7":
            screen_dispatch()
        elif choice == "8":
            screen_settings()

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
