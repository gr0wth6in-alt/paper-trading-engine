# Deploying the paper engine and Hermes on a VPS

This guide moves the paper engine to the VPS that already runs Hermes (SumoPod 1-click
template), so Hermes can paper-trade 24/7 over `localhost`. It targets **Ubuntu 24.04**
(Python 3.12 is the default there) with fallbacks for Ubuntu 22.04 and Debian 12.

What you end up with:

- `paper-engine.service` (systemd, user `paper`) on `127.0.0.1:8000`, one uvicorn worker,
  serving the API and the built React terminal. **Nothing is opened to the internet.**
- A **fresh** database `data/paper-hermes.db` (your Windows account stays on the PC).
- Hermes connected through the MCP tool server, trading on a 15-minute cron job.
- The terminal reachable from your PC through an SSH tunnel.
- 2 GB swap, a memory cap on the engine, capped logs and daily database backups.

Everything stays virtual: no exchange keys, no real orders. Commands prefixed with `sudo`
run as an admin user; `sudo -u paper` runs as the engine user.

Values to substitute: `<vps>` (IP or hostname), `<admin>` (your SSH login user),
`<hermes-user>` (found in step 0).

---

## 0. Check the server first

One line to see the OS, Python, memory, disk and systemd:

```bash
cat /etc/os-release; python3 --version; free -h; df -h /; systemctl --version | head -1; uname -m
```

| `VERSION_ID` in `/etc/os-release` | Python setup to follow in step 4 |
| --- | --- |
| Ubuntu `24.04` | 4A (default `python3` is 3.12) |
| Ubuntu `22.04` | 4B (deadsnakes PPA) |
| Debian `12` | 4C (pyenv) |
| Debian `13` (trixie) | 4D (default `python3` is 3.13; verified compatible) |

`uname -m` should print `x86_64` or `aarch64`; both work.

Find out how SumoPod runs Hermes (native process or Docker, and as which user):

```bash
command -v hermes; ps -eo user,pid,cmd | grep -i [h]ermes; \
  (docker ps --format '{{.Names}}  {{.Image}}' 2>/dev/null | grep -i hermes); \
  sudo ls -d /root/.hermes /home/*/.hermes 2>/dev/null
```

- **A `hermes` process owned by a normal user, with `~/.hermes` in that user's home**:
  native install. Note that user as `<hermes-user>` and use step 11A.
- **Only a Docker container matches**: Hermes runs in a container. Use step 11C.
- **Hermes runs as `root`**: works, but prefer the steps exactly as written so the engine
  database and operator token stay out of Hermes' reach.

Also list what is already listening, so the firewall step does not cut off Hermes'
dashboard or gateway:

```bash
sudo ss -tlnp
```

## 1. Security first

1. **Change the VPS password** that was shared in a chat earlier (`passwd`), and the
   SumoPod panel password if it is the same one.
2. Use SSH keys. From Windows PowerShell:
   ```powershell
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <admin>@<vps> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
   ```
   Confirm `ssh <admin>@<vps>` logs in **without** a password before continuing.
3. Disable SSH password login:
   ```bash
   echo -e "PasswordAuthentication no\nKbdInteractiveAuthentication no" | sudo tee /etc/ssh/sshd_config.d/10-keys-only.conf
   sudo sshd -t && sudo systemctl reload ssh || sudo systemctl reload sshd
   ```
4. Firewall. Allow SSH, plus any port from `ss -tlnp` that you still use from outside
   (for example a Hermes web dashboard). **Never allow 8000 or 8765.**
   ```bash
   sudo apt-get install -y ufw
   sudo ufw allow OpenSSH
   # sudo ufw allow <port>/tcp   # only for ports you really need from outside
   sudo ufw enable && sudo ufw status verbose
   ```

## 2. Create the engine user and directories

```bash
sudo useradd --system --create-home --home-dir /var/lib/paper --shell /usr/sbin/nologin paper
sudo mkdir -p /opt/paper-trading-engine /etc/paper-engine
sudo chown paper:paper /opt/paper-trading-engine
```

The engine runs as `paper`. Hermes keeps running as `<hermes-user>` and only receives the
agent token, never the operator token or the database.

## 3. Transfer the code

Choose **A** (scp, simplest) or **B** (git).

### 3A. Release archive + scp (recommended)

On Windows, from the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\package-release.ps1
scp release\paper-trading-engine-*.tar.gz <admin>@<vps>:/tmp/
```

The script builds the frontend (`npm run build`) and packs code plus `frontend/dist`. It
refuses to include `.env`, `data/`, databases, `.venv` or `node_modules`.

On the VPS:

```bash
sudo -u paper tar -xzf /tmp/paper-trading-engine-*.tar.gz -C /opt/paper-trading-engine
rm /tmp/paper-trading-engine-*.tar.gz
```

### 3B. Git (private repository)

The project is not a git repository yet. On Windows (`.gitignore` already excludes `.env`,
`data/`, databases and `frontend/dist`):

```powershell
git init
git add .
git status          # check: no .env, no data/, no *.db
git commit -m "Paper engine with Hermes agent"
git remote add origin git@github.com:<you>/paper-trading-engine.git   # a PRIVATE repo
git push -u origin main
```

On the VPS (add a read-only deploy key for the `paper` user first):

```bash
sudo -u paper git clone git@github.com:<you>/paper-trading-engine.git /opt/paper-trading-engine
```

`frontend/dist` is not in git. Build it on Windows (`build-frontend.cmd`) and copy it:

```powershell
scp -r frontend\dist <admin>@<vps>:/tmp/dist
```
```bash
sudo rm -rf /opt/paper-trading-engine/frontend/dist
sudo mv /tmp/dist /opt/paper-trading-engine/frontend/dist
```

### Permissions (both options)

```bash
cd /opt/paper-trading-engine
sudo chown -R paper:paper .
sudo find . -type d -exec chmod 755 {} +
sudo find . -type f -exec chmod 644 {} +
sudo chmod 755 deploy/*.sh
sudo -u paper mkdir -p data && sudo chmod 700 data
```

Code and the venv stay world-readable so Hermes can start the MCP server; `.env` (step 6)
and `data/` are private to `paper`.

## 4. Install Python 3.12

### 4A. Ubuntu 24.04

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev build-essential sqlite3 curl
python3 --version        # Python 3.12.x
PY=python3
```

### 4B. Ubuntu 22.04 (deadsnakes)

```bash
sudo apt-get update
sudo apt-get install -y software-properties-common build-essential sqlite3 curl
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version
PY=python3.12
```

Do not replace the system `python3`; Ubuntu tools depend on 3.10.

### 4C. Debian 12 (pyenv)

Debian 12 ships Python 3.11, which is too old. Build 3.12 with pyenv into `/opt/python`:

```bash
sudo apt-get update
sudo apt-get install -y build-essential sqlite3 curl git libssl-dev zlib1g-dev libbz2-dev \
  libreadline-dev libsqlite3-dev libncursesw5-dev xz-utils tk-dev libxml2-dev \
  libxmlsec1-dev libffi-dev liblzma-dev
sudo git clone --depth 1 https://github.com/pyenv/pyenv.git /opt/pyenv
sudo PYENV_ROOT=/opt/pyenv /opt/pyenv/bin/pyenv install 3.12
PY=$(ls -d /opt/pyenv/versions/3.12*/bin/python3.12 | tail -1)
$PY --version
```

The build takes 5–10 minutes on 2 vCPUs. Set up swap (step 7) first if it runs out of memory.

### 4D. Debian 13 (trixie)

Python 3.13 is the default and works as-is. Every pinned dependency ships a prebuilt
cp313 wheel for x86_64 and aarch64, so no compiler is needed.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv sqlite3 curl ca-certificates
python3 --version        # Python 3.13.x
PY=python3
```

- `python3-venv` is **required**: Debian ships `ensurepip` separately, and `python3 -m venv`
  fails without it.
- `python3-full` is not needed (it adds IDLE, Tk and other extras).
- `build-essential` and `python3-dev` are not needed. Install them only if pip ever reports
  that it is building a wheel from source.
- Debian marks the system Python as externally managed (PEP 668). That is fine: everything
  installs into `.venv`. Never use `pip install --break-system-packages`.

## 5. Create the virtual environment

```bash
cd /opt/paper-trading-engine
sudo -u paper $PY -m venv .venv
sudo -u paper .venv/bin/python -m pip install --upgrade pip
# Install the versions tested on Windows, minus the Windows-only packages...
grep -vE '^(pywin32|winloop)==' requirements.lock | sudo -u paper tee /tmp/req-linux.txt >/dev/null
# --only-binary: never compile on a 2 GB VPS; fail fast instead if a wheel is missing.
sudo -u paper .venv/bin/python -m pip install --only-binary=:all: -r /tmp/req-linux.txt
# ...then the project itself with the Hermes MCP extra (adds Linux-only extras such as uvloop).
sudo -u paper .venv/bin/python -m pip install -e ".[agent]"
sudo -u paper .venv/bin/python -m pip check
sudo -u paper sh -c '.venv/bin/python -m pip freeze --exclude-editable > requirements-linux.lock'
rm /tmp/req-linux.txt
```

`pip check` must print `No broken requirements found.` Keep `requirements-linux.lock`: it
records exactly what runs on the server.

## 6. Configure `.env`

```bash
cd /opt/paper-trading-engine
sudo -u paper .venv/bin/python -m paper_engine.configure                 # creates .env + operator token
sudo -u paper .venv/bin/python -m paper_engine.configure --agent-token   # adds PAPER_AGENT_TOKEN
sudo -u paper sed -i 's#^PAPER_DB_PATH=.*#PAPER_DB_PATH=data/paper-hermes.db#' .env
sudo chmod 600 .env
sudo -u paper grep -E '^PAPER_(DB_PATH|EXCHANGE|SYMBOL_SELECTION|CORS_ORIGINS|AGENT_[A-Z_]+)=' .env | grep -v TOKEN
```

Expected: `PAPER_DB_PATH=data/paper-hermes.db` (fresh account), `PAPER_EXCHANGE=apex`,
`PAPER_CORS_ORIGINS=[]`, and the agent limits:

| Setting | Default | Meaning |
| --- | --- | --- |
| `PAPER_AGENT_MIN_OPEN_INTERVAL_SECONDS` | `900` | One Hermes entry per 15 minutes (minimum 300) |
| `PAPER_AGENT_DAILY_LOSS_PCT` | `0.03` | Breaker at 3% of the start-of-day wallet (UTC) |
| `PAPER_AGENT_MAX_RISK_PER_TRADE_PCT` | `0.01` | Loss at the stop-loss ≤ 1% of wallet |
| `PAPER_AGENT_MAX_OPEN_POSITIONS` | `3` | Open Hermes positions at once |
| `PAPER_AGENT_MAX_LEVERAGE` | `10` | Leverage cap for Hermes |

Never paste `.env` into chat or logs. To read a token later:
`sudo -u paper grep '^PAPER_API_TOKEN=' /opt/paper-trading-engine/.env`.

## 7. Swap (2 GB VPS)

```bash
sudo bash /opt/paper-trading-engine/deploy/setup-swap.sh        # 2G
# sudo bash /opt/paper-trading-engine/deploy/setup-swap.sh 4G   # 4G variant if disk allows
swapon --show; free -h
```

The script is safe to re-run. It adds an `/etc/fstab` entry and sets `vm.swappiness=10`
so swap is used only under real memory pressure. Check free disk with `df -h /` first.

Rough memory budget: engine 250–350 MB, news parser worker 60–80 MB, MCP server ~60 MB,
Hermes 200–400 MB. The engine service is capped at `MemoryHigh=700M` / `MemoryMax=900M`.

## 8. Install the systemd service

```bash
cd /opt/paper-trading-engine
sudo cp deploy/paper-engine.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp deploy/journald-paper.conf /etc/systemd/journald.conf.d/paper.conf
sudo systemctl restart systemd-journald
sudo systemctl daemon-reload
sudo systemctl enable --now paper-engine
systemctl status paper-engine --no-pager
journalctl -u paper-engine -n 50 --no-pager
```

Daily backups at 00:15 UTC into `data/backups` (14 kept):

```bash
sudo cp deploy/paper-backup.service deploy/paper-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paper-backup.timer
sudo systemctl start paper-backup.service && ls -l /opt/paper-trading-engine/data/backups
```

## 9. Health checks

```bash
curl -s http://127.0.0.1:8000/health; echo
# expected: {"status":"ok","mode":"paper","hermes":"paused"}
cd /opt/paper-trading-engine
sudo -u paper .venv/bin/python -m paper_engine.smoke --exchange apex   # public ApeX data reachable?
sudo -u paper .venv/bin/python -m tests.live_news_check | head -40     # optional: RSS sources
ss -tlnp | grep 8000                                                  # must show 127.0.0.1:8000 only
```

If the smoke check times out, ApeX may be unreachable from the VPS region or network. Do
not bypass geographic restrictions; see Troubleshooting.

## 10. Open the terminal from your PC

```powershell
ssh -N -L 8000:127.0.0.1:8000 <admin>@<vps>
```

Keep that window open and browse to <http://127.0.0.1:8000>. Connect with
`PAPER_API_TOKEN` from the VPS `.env`. If the Windows engine still uses port 8000, tunnel
`8001:127.0.0.1:8000` and open <http://127.0.0.1:8001> instead.

The **Hermes agent** bar under the account bar shows **Paused** on a fresh database.

## 11. Connect Hermes

### 11A. Native Hermes (recommended)

Give Hermes only the agent token, in a file its user can read:

```bash
TOKEN=$(sudo -u paper grep '^PAPER_AGENT_TOKEN=' /opt/paper-trading-engine/.env | cut -d= -f2-)
printf 'PAPER_AGENT_TOKEN=%s\nPAPER_ENGINE_URL=http://127.0.0.1:8000\n' "$TOKEN" \
  | sudo tee /etc/paper-engine/agent.env >/dev/null
unset TOKEN
sudo chown root:$(id -gn <hermes-user>) /etc/paper-engine/agent.env
sudo chmod 640 /etc/paper-engine/agent.env
```

Check that the Hermes user can start the server (it must list 8 tools):

```bash
sudo -u <hermes-user> /opt/paper-trading-engine/.venv/bin/python -c "import sys; print(sys.version)"
cd /opt/paper-trading-engine && sudo -u <hermes-user> \
  env $(sudo cat /etc/paper-engine/agent.env | xargs) .venv/bin/python -m tests.live_mcp_check
```

Add the server to Hermes. As `<hermes-user>`, edit `~/.hermes/config.yaml` and paste the
`mcp_servers.paper` block from `docs/hermes/config.example.yaml` (option A uses
`deploy/hermes-mcp.sh`, which reads `/etc/paper-engine/agent.env`). Then:

```bash
hermes mcp            # the "paper" server should be listed with its tools
```

Install the trading skill and schedule it:

```bash
mkdir -p ~/.hermes/skills/finance
cp -r /opt/paper-trading-engine/docs/hermes/skills/paper-trader ~/.hermes/skills/finance/
hermes cron create "every 15m" \
  "Run one paper-trading cycle with the paper MCP tools. Follow the skill exactly; doing nothing is fine." \
  --skill paper-trader
hermes cron list
```

About 96 runs a day use your LLM API key. Pin a cheaper model for cron only with
`hermes config set cron.model <model-name>`, or schedule `"every 30m"`. See
`docs/hermes/README.md`.

### 11B. Hermes runs as root

Use 11A with `<hermes-user>` = `root`; the config lives at `/root/.hermes/config.yaml`.

### 11C. Hermes in Docker

The container cannot run the host venv, so serve the tools over HTTP on the Docker bridge
with their own token:

```bash
ip -4 addr show docker0          # usually 172.17.0.1
TOKEN=$(sudo -u paper grep '^PAPER_AGENT_TOKEN=' /opt/paper-trading-engine/.env | cut -d= -f2-)
MCP=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
printf 'PAPER_AGENT_TOKEN=%s\nPAPER_MCP_TOKEN=%s\n' "$TOKEN" "$MCP" | sudo tee /etc/paper-engine/mcp-http.env >/dev/null
sudo chown root:root /etc/paper-engine/mcp-http.env && sudo chmod 600 /etc/paper-engine/mcp-http.env
echo "PAPER_MCP_TOKEN for Hermes: $MCP"; unset TOKEN MCP
sudo cp /opt/paper-trading-engine/deploy/paper-mcp-http.service /etc/systemd/system/
# edit --host in the unit if docker0 is not 172.17.0.1
sudo systemctl daemon-reload && sudo systemctl enable --now paper-mcp-http
sudo ufw allow in on docker0 to 172.17.0.1 port 8765 proto tcp
```

The server refuses `0.0.0.0` and rejects requests without the bearer token. In the
container's Hermes config use option C from `docs/hermes/config.example.yaml`
(`url: http://172.17.0.1:8765/mcp` plus the `Authorization` header). If the container uses
host networking instead, run it on `127.0.0.1` and set `--host 127.0.0.1` in the unit.

## 12. First-run checklist

1. `curl -s 127.0.0.1:8000/health` reports `"hermes":"paused"`.
2. In the terminal, the Execution feed is live and the News page lists sources as ok.
3. Check the Hermes bar limits: 15 min, 3% daily, 1% per trade, 3 positions, 10×.
4. Ask Hermes once by hand: `hermes chat -q "/paper-trader run one cycle"`. It should call
   `get_guardrails`, see it is paused, and do nothing.
5. Click **Resume Hermes** and confirm. The next cron run may open one position.
6. Watch the first hour: positions get a **HERMES** badge, closed trades show Hermes' entry
   and exit reasons in **Journal**, and rejected attempts appear in
   `GET /api/v1/agent/events` (operator token).
7. Click **Pause Hermes** any time. New entries stop at once; stops and targets keep running.

## 13. Operations

### Update

```powershell
powershell -ExecutionPolicy Bypass -File deploy\package-release.ps1
scp release\paper-trading-engine-*.tar.gz <admin>@<vps>:/tmp/
```
```bash
sudo systemctl start paper-backup.service           # backup first
sudo systemctl stop paper-engine
sudo -u paper tar -xzf /tmp/paper-trading-engine-*.tar.gz -C /opt/paper-trading-engine
cd /opt/paper-trading-engine && sudo chmod 755 deploy/*.sh
sudo -u paper .venv/bin/python -m pip install -e ".[agent]" && sudo -u paper .venv/bin/python -m pip check
sudo systemctl start paper-engine && journalctl -u paper-engine -n 30 --no-pager
```

Extracting over the old tree keeps `.env`, `data/` and `.venv`. Keep the previous tarball
for rollback. The database schema only moves forward: an older release cannot open a
database that a newer one upgraded, so restore the pre-update backup when rolling back.

### Restore a backup

```bash
sudo systemctl stop paper-engine
sudo -u paper cp data/backups/paper-hermes-<stamp>.db data/paper-hermes.db
sudo -u paper rm -f data/paper-hermes.db-wal data/paper-hermes.db-shm
sudo systemctl start paper-engine
```

### Revoke or rotate the Hermes token

Remove (revoke) or regenerate (`python -m paper_engine.configure --agent-token` after
deleting the line) `PAPER_AGENT_TOKEN` in `.env`, update `/etc/paper-engine/agent.env`,
then `sudo systemctl restart paper-engine`. Without a token the agent API is disabled.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Service restarts in a loop, log shows `Database is in use` | Two engines on one database. Run exactly one service; stop any manual `python -m paper_engine`. |
| Startup fails during symbol discovery | ApeX unreachable from the VPS. Check DNS/TLS with the smoke test. Temporarily set `PAPER_SYMBOL_SELECTION=fixed`. |
| `Killed` / OOM in `journalctl -k` | Check `swapon --show` and `free -h`; add swap (step 7) or lower `PAPER_TOP_SYMBOLS_COUNT`. |
| Hermes gets `unauthorized` | Agent token in `agent.env` does not match `.env`, or the engine was not restarted after a change. |
| Hermes gets `forbidden_for_agent` | It called an operator route; only the MCP tools are supported. |
| `agent_paused` | Resume from the terminal's Hermes bar. |
| `agent_cooldown` | Normal: one entry per 15 minutes. |
| `agent_daily_loss_limit` | Breaker tripped; entries resume at 00:00 UTC. |
| `agent_risk_limit` / `agent_stop_beyond_liquidation` | Order too large for its stop; Hermes should resize (the skill does once). |
| `agent_valuation_unavailable`, `stale_quote` | Market data not live; check the feed in the terminal. |
| News page shows `Parser restarted` for every source | The parser worker cannot start under the service sandbox; check `journalctl -u paper-engine` and report the error. |
| Browser cannot connect | Tunnel window closed, or wrong local port. Never open port 8000 in the firewall instead. |

What could not be verified from Windows: the exact SumoPod image, how its Hermes is
installed, and the systemd sandbox on your kernel. Steps 0, 9 and 12 exist to check these.
