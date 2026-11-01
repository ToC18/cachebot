import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
import time

# Daemon log redirect or console UTF-8
if '--daemon' in sys.argv:
    _log_f = open('app.log', 'a', encoding='utf-8', buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
else:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

CLOUDFLARED_PATH = os.path.join(PROJECT_DIR, "cloudflared.exe")
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
TUNNEL_LOG = os.path.join(PROJECT_DIR, "tunnel.log")
LOCAL_TARGET = "127.0.0.1:8000"

from app.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Tunnel providers
#   localhostrun - https://*.lhr.life via built-in Windows OpenSSH (no signup,
#                  not blocked like trycloudflare.com on mobile operators)
#   cloudflare   - https://*.trycloudflare.com (often blocked without VPN)
# Select with TUNNEL_PROVIDER in .env
# ---------------------------------------------------------------------------
PROVIDERS = {
    "localhostrun": {
        "cmd": [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=NUL" if os.name == "nt" else "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-T",
            "-R", f"80:{LOCAL_TARGET}",
            "nokey@localhost.run",
            "--", "--output", "json",
        ],
        "pattern": re.compile(r"https://[a-zA-Z0-9-]+\.lhr\.life"),
    },
    "cloudflare": {
        "cmd": [CLOUDFLARED_PATH, "tunnel", "--url", f"http://{LOCAL_TARGET}"],
        "pattern": re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"),
    },
}

current_url = None
first_url_event = threading.Event()
stop_event = threading.Event()
tunnel_proc = None


def log_tunnel(line: str):
    try:
        with open(TUNNEL_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(line if line.endswith("\n") else line + "\n")
    except Exception:
        pass


def update_env_url(target: str):
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if "WEBAPP_URL=" in content:
        content = re.sub(r"WEBAPP_URL=.*", f"WEBAPP_URL={target}", content)
    else:
        content += f"\nWEBAPP_URL={target}\n"

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    os.environ["WEBAPP_URL"] = target


def on_new_url(base_url: str):
    """Called from the tunnel thread whenever the provider gives us an address."""
    global current_url
    target = f"{base_url}/app?v=4.0"
    if target == current_url:
        return
    current_url = target

    print("\n" + "=" * 60)
    print(f"[OK] ACTIVE MINI APP URL: {target}")
    print("=" * 60 + "\n", flush=True)

    update_env_url(target)
    settings.webapp_url = target
    first_url_event.set()

    # If the bot is already running, refresh the Telegram menu button live
    main_mod = sys.modules.get("main")
    loop = getattr(main_mod, "main_loop", None) if main_mod else None
    if loop is not None and loop.is_running():
        # reply keyboard has no URL inside, so only the menu button needs refreshing
        asyncio.run_coroutine_threadsafe(main_mod.apply_webapp_url(target, notify=False), loop)


def tunnel_worker(provider: str):
    """Keeps the tunnel alive: restarts it whenever the process exits."""
    global tunnel_proc
    cfg = PROVIDERS[provider]
    backoff = 3

    while not stop_event.is_set():
        log_tunnel(f"--- starting {provider} tunnel at {time.ctime()} ---")
        try:
            tunnel_proc = subprocess.Popen(
                cfg["cmd"],
                stdin=subprocess.PIPE,  # keep stdin open, otherwise ssh session closes
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as e:
            print(f"[Tunnel] Cannot start {provider}: {e}", flush=True)
            first_url_event.set()
            return

        started = time.time()
        for line in tunnel_proc.stdout:
            log_tunnel(line)
            match = cfg["pattern"].search(line)
            if match:
                on_new_url(match.group(0))
                backoff = 3

        tunnel_proc.wait()
        if stop_event.is_set():
            break
        # Quick failures -> grow backoff, long-lived sessions -> retry fast
        if time.time() - started > 60:
            backoff = 3
        else:
            backoff = min(backoff * 2, 60)
        print(f"[Tunnel] {provider} disconnected (code {tunnel_proc.returncode}), reconnecting in {backoff}s...", flush=True)
        time.sleep(backoff)


def ensure_docker_services():
    """Start Redis + Postgres from docker-compose.yml if Docker is available."""
    if not shutil.which("docker"):
        print("Docker not found - make sure Redis and Postgres are running.")
        return
    print("Starting Redis + Postgres (docker compose up -d)...", flush=True)
    try:
        res = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=PROJECT_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        if res.returncode != 0:
            print(f"[Docker] warning: {res.stderr.strip()[-500:]}")
        else:
            time.sleep(3)  # give Postgres a moment to accept connections
    except Exception as e:
        print(f"[Docker] warning: {e}")


def main():
    provider = (settings.tunnel_provider or "localhostrun").lower()
    if provider not in PROVIDERS:
        print(f"Unknown TUNNEL_PROVIDER={provider}, falling back to localhostrun")
        provider = "localhostrun"

    print("=" * 60)
    print(f"       CacheBot + Mini App (tunnel: {provider})")
    print("=" * 60, flush=True)

    ensure_docker_services()

    print(f"Starting {provider} tunnel to {LOCAL_TARGET}...", flush=True)
    threading.Thread(target=tunnel_worker, args=(provider,), daemon=True).start()

    if not first_url_event.wait(timeout=45) or not current_url:
        print("Warning: tunnel URL not detected yet, starting server anyway "
              "(menu button will be updated when the tunnel comes up)...")

    print("Starting FastAPI and Telegram polling...", flush=True)
    import uvicorn
    from main import app
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        stop_event.set()
        if tunnel_proc and tunnel_proc.poll() is None:
            tunnel_proc.terminate()


if __name__ == "__main__":
    main()
