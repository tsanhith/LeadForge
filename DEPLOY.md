# Deploying LeadForge (free, always-on)

This guide deploys LeadForge to a **free-forever Linux VM** on **Oracle Cloud Always Free**.
For 3–4 users the default setup is all you need: the built-in `inprocess` queue + SQLite — no
Redis, no extra services.

The same steps work on any Ubuntu/Debian VM (Google Cloud `e2-micro` always-free, a cheap VPS,
etc.). Only the "Create the VM" section is Oracle-specific.

> **Why a VM and not Render/Railway/Fly free tiers?** LeadForge keeps state in a SQLite file on
> disk and runs per-lead jobs that take minutes. Most free PaaS tiers use an ephemeral
> filesystem (SQLite wiped on restart) and sleep idle apps (jobs killed mid-run). A free VM has
> a real persistent disk and never sleeps.

---

## 1. Create the VM (Oracle Cloud Always Free)

1. Sign up at <https://www.oracle.com/cloud/free/> (a credit card is required for identity
   verification; the Always Free resources are not charged).
2. **Compute → Instances → Create instance.**
   - **Image:** Canonical Ubuntu 22.04 (or 24.04).
   - **Shape:** `VM.Standard.A1.Flex` (Ampere ARM) — pick **1 OCPU / 6 GB RAM**. This is within
     the Always Free allowance and gives plenty of headroom for pandas + the pipeline.
     (If ARM capacity is unavailable in your region, `VM.Standard.E2.1.Micro` works but is
     tighter at 1 GB RAM.)
   - **SSH keys:** upload your public key (or let Oracle generate one and download it).
3. **Networking:** keep the default VCN. After the instance is up, open the firewall:
   - **VCN → Security List → Add Ingress Rules:** allow TCP **80** and **443** from `0.0.0.0/0`.
4. Note the instance's **public IP**.

> **DNS (recommended):** point a domain/subdomain (e.g. `leadforge.example.com`) at the public
> IP with an `A` record. This lets Caddy issue a real HTTPS certificate automatically. You can
> skip DNS and use the raw IP, but then you only get HTTP (see the IP-only note in step 5).

---

## 2. First login & system setup

SSH in (default user is `ubuntu` on Ubuntu images):

```bash
ssh -i /path/to/key ubuntu@YOUR_PUBLIC_IP
```

Install Python and git, and open the OS firewall (Oracle images ship with iptables locked down):

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git

# Oracle Ubuntu images block ports by default — allow HTTP/HTTPS at the OS level too.
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save    # if missing: sudo apt install -y iptables-persistent
```

---

## 3. Get the code & install

Run the app under its own unprivileged user so it isn't tied to your login:

```bash
sudo useradd --system --create-home --shell /bin/bash leadforge
sudo -iu leadforge

# (now acting as the leadforge user)
git clone https://github.com/tsanhith/LeadForge.git ~/app    # or your fork/remote
cd ~/app
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

---

## 4. Configure `.env`

```bash
cp .env.example .env
nano .env
```

Set at minimum (see `README.md` for the full table):

```ini
# The engine — without an LLM key nothing generates. At least one of:
OPENROUTER_API_KEY=sk-or-...
# NVIDIA_NIM_API_KEY=nvapi-...

# Login
SESSION_SECRET=<paste output of: python3 -c "import secrets;print(secrets.token_hex(32))">
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=<a strong password>

# Public surface — must match your real URL so the unsubscribe link works
PUBLIC_BASE_URL=https://leadforge.example.com
COMPANY_POSTAL_ADDRESS=Your Co, 123 Street, City, Country

# Channels stay on the safe console mock until your creds arrive:
EMAIL_PROVIDER=console
WHATSAPP_PROVIDER=console
```

Generate the session secret in one line:

```bash
.venv/bin/python -c "import secrets;print(secrets.token_hex(32))"
```

Leave `QUEUE_BACKEND=inprocess` and the default `DATABASE_URL` — perfect for this scale.

Exit back to your sudo user:

```bash
exit        # leaves the leadforge shell
```

---

## 5. Run it as a service (systemd + Caddy)

### 5a. systemd unit — keeps the app running & restarts on reboot

Create `/etc/systemd/system/leadforge.service`:

```bash
sudo tee /etc/systemd/system/leadforge.service > /dev/null <<'EOF'
[Unit]
Description=LeadForge
After=network.target

[Service]
Type=simple
User=leadforge
WorkingDirectory=/home/leadforge/app
EnvironmentFile=/home/leadforge/app/.env
ExecStart=/home/leadforge/app/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now leadforge
sudo systemctl status leadforge --no-pager
```

The app now listens on `127.0.0.1:8000` (localhost only — Caddy will expose it publicly with
HTTPS). One uvicorn worker is correct here: the in-process queue and SQLite assume a single
process.

### 5b. Caddy — HTTPS reverse proxy (automatic certificates)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Replace Caddy's config with a one-line reverse proxy:

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
leadforge.example.com {
    reverse_proxy 127.0.0.1:8000
}
EOF

sudo systemctl restart caddy
```

Caddy fetches a free Let's Encrypt certificate automatically. Visit
`https://leadforge.example.com` and log in with the admin from `.env`.

> **No domain?** Replace the first line with `:80` instead of `leadforge.example.com`. You'll
> get plain HTTP on the IP (`http://YOUR_PUBLIC_IP`) with no certificate — fine for a quick
> trial, but set up DNS before sending real outreach. Also set `PUBLIC_BASE_URL` to match.

---

## 6. Back up the SQLite database

The whole app state is one file: `/home/leadforge/app/leadforge.db`. Oracle can occasionally
reclaim idle free instances, so keep off-box backups. A nightly local snapshot (use SQLite's
`.backup` so it's consistent even while the app is writing):

```bash
sudo -iu leadforge bash -c 'mkdir -p ~/backups && cat > ~/backup.sh' <<'EOF'
#!/usr/bin/env bash
set -e
cd /home/leadforge/app
STAMP=$(date +%F)
sqlite3 leadforge.db ".backup '/home/leadforge/backups/leadforge-$STAMP.db'"
# keep the last 14 days
find /home/leadforge/backups -name 'leadforge-*.db' -mtime +14 -delete
EOF

sudo apt install -y sqlite3
sudo -u leadforge chmod +x /home/leadforge/backup.sh

# run nightly at 03:30
( sudo -u leadforge crontab -l 2>/dev/null; echo "30 3 * * * /home/leadforge/backup.sh" ) | sudo -u leadforge crontab -
```

For real off-box safety, also copy backups elsewhere — e.g. `rclone` to a free cloud bucket, or
periodically `scp` them to your laptop. Don't rely solely on the VM's disk.

---

## 7. Day-to-day operations

```bash
# logs (live)
sudo journalctl -u leadforge -f

# restart after a config change
sudo systemctl restart leadforge

# update to the latest code
sudo -iu leadforge bash -lc 'cd ~/app && git pull && .venv/bin/pip install -r requirements.txt'
sudo systemctl restart leadforge
```

`.env` changes require a restart (`systemctl restart leadforge`). The SQLite schema
auto-migrates on startup, so a `git pull` + restart is the whole upgrade.

---

## Going live with real sending

This deploy keeps email and WhatsApp on the `console` mock. When credentials arrive, edit
`.env` and restart — see **README → "Going live"**:

- **Email:** `EMAIL_PROVIDER=smtp` (+ `SMTP_*`) or `resend` (+ `RESEND_API_KEY`), a real
  `EMAIL_FROM`, and **SPF + DKIM + DMARC** on the sending domain first.
- **WhatsApp:** `WHATSAPP_PROVIDER=meta`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and a
  pre-approved `WHATSAPP_TEMPLATE_NAME`.

If you later need to scale past a single box, switch `QUEUE_BACKEND=arq` + Redis and run the
`arq` worker (README → "Horizontal scaling"). For 3–4 users you won't need to.
