# Testing Setup Guide (Server Host & Client PC)

This guide walks you through testing the Gaming MIS prototype across two machines:
1. **Laptop (Server Host)**: Runs the Django web application and PostgreSQL database inside Docker.
2. **Other PC (Client Machine)**: Runs the Windows background agent (`cafe-agent.exe`) to report live hardware activity (keyboard, mouse, gamepad).

---

## 1. Prerequisites & Installations

| Machine | Required Software | What needs to be installed? |
|---|---|---|
| **Laptop (Server)** | Docker Desktop, Python 3.10+ | • Install & run **Docker Desktop** (ensure it is running and unpaused).<br>• Python 3.10+ for generating tokens and running migrations if needed. |
| **Other PC (Client)** | Windows 10 or 11 | **Nothing!** No Docker, Python, Go, or runtime dependencies.<br>Only copy the pre-built `agent/cafe-agent.exe` binary. |

---

## 2. Server Configuration on the Laptop

### Step 2.1: Generate Agent Token & Secret Hash
The client agent authenticates with a Bearer token, and the server validates its SHA-256 hash.

Run this command in PowerShell on your laptop:
```powershell
python -c "import secrets, hashlib; t = secrets.token_urlsafe(32); print('AGENT_TOKEN (save this for client PC):', t); print('AGENT_TOKEN_SHA256=' + hashlib.sha256(t.encode()).hexdigest())"
```

1. **Copy the plaintext `AGENT_TOKEN`** somewhere handy (you will pass this to the client PC).
2. Note the generated `AGENT_TOKEN_SHA256` hash.

### Step 2.2: Configure `deploy/.env`
Open `deploy/.env` (or copy from `deploy/.env.example` if not already created) and set:
```env
DJANGO_SECRET_KEY=<your-secret-key>
POSTGRES_PASSWORD=<your-db-password>
AGENT_TOKEN_SHA256=<the-sha256-hash-from-step-2.1>

# Allow access from local network and tunnels:
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.trycloudflare.com,*
DJANGO_SECURE_COOKIES=0
```
> **Note:** `DJANGO_SECURE_COOKIES=0` allows browsers on the local network to log in over plain HTTP (`http://<IP>:8000`).

### Step 2.3: Check Docker Port Mapping
In `deploy/docker-compose.yml`, ensure the web service binds to all interfaces:
```yaml
    ports:
      - "8000:8000"
```
*(Avoid `127.0.0.1:8000:8000` because that only listens on the laptop's loopback and blocks other network devices).*

---

## 3. Start the Server on the Laptop

1. Open PowerShell in the `deploy/` directory and start the stack:
   ```powershell
   cd deploy
   docker compose up -d --build
   ```

2. Confirm containers are running:
   ```powershell
   docker compose ps
   ```

3. Create your staff/admin login:
   ```powershell
   docker compose exec web python manage.py createsuperuser
   ```
   Follow the prompts to enter a username, email (optional), and password.

---

## 4. Configure Café Settings (Crucial for First-Time Setup)

By default, unknown PCs are rejected with HTTP 403, and idle timeouts wait 10 minutes. To make testing immediate:

1. Open your browser on the laptop: `http://localhost:8000/admin/`
2. Log in with the superuser credentials created in Step 3.
3. Navigate to **Status** → **Café settings** (or Café configuration):
   - **Allow new PCs:** ✅ **Ticked** *(Crucial: must be ticked to register new PCs)*
   - **Idle threshold (s):** Set to `60`
   - **Heartbeat interval (s):** Set to `30`
   - **Offline timeout (s):** Set to `60`
4. Click **Save**.

---

## 5. Laptop Network & Windows Firewall

### Step 5.1: Find Laptop's Local IP Address
Run in PowerShell on your laptop:
```powershell
ipconfig
```
Look for the **IPv4 Address** under your active Wi-Fi or Ethernet adapter (e.g. `192.168.1.45`).

### Step 5.2: Allow Port 8000 Through Windows Firewall
By default, Windows Defender Firewall blocks incoming connections from the local network.

Run in an Administrator PowerShell on the laptop:
```powershell
New-NetFirewallRule -DisplayName "Gaming_MIS_8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

---

## 6. Running the Agent on the Client PC

1. **Copy the Executable:**
   Copy `agent/cafe-agent.exe` from your laptop to the other PC (via USB drive, shared folder, or direct transfer). Place it anywhere convenient (e.g., `C:\cafe-agent\cafe-agent.exe`).

2. **Run the Agent:**
   Open Command Prompt or PowerShell on the other PC and execute:
   ```cmd
   cafe-agent.exe -url http://<LAPTOP_IP>:8000/api/v1/heartbeat -token <AGENT_TOKEN>
   ```
   *(Replace `<LAPTOP_IP>` with your laptop's local IP, e.g. `192.168.1.45`, and `<AGENT_TOKEN>` with the plain token from Step 2.1).*

3. **Verify Process in Task Manager:**
   The agent runs silently with no window. Open **Task Manager** → **Details** tab and verify `cafe-agent.exe` is running with ~0% CPU and ~5-10 MB memory.

---

## 7. Verify Dashboard & Statuses

1. On your laptop (or in a browser on the client PC), visit:
   `http://localhost:8000/staff/` (or `http://<LAPTOP_IP>:8000/staff/`)
2. Log in with your staff account.
3. Verify the status lifecycle:
   - **Initial Boot:** Within 0–30s, a tile with the other PC's hostname appears.
   - **In Use:** Type on the keyboard or move the mouse/gamepad on the other PC. The tile shows **In Use** (Green).
   - **Idle:** Leave the other PC untouched for > 60s. The tile turns **Idle** (Amber).
   - **Active Again:** Move the mouse on the other PC. Within ~30s, it transitions back to **In Use**.
   - **Off / Shutdown:** Close `cafe-agent.exe` in Task Manager or shut down the client PC. The tile turns **Off** (Grey) after the offline timeout.

---

## 8. Alternative: Testing via Cloudflare Tunnel

If your local Wi-Fi router has "Client Isolation" enabled (devices cannot reach each other directly over LAN):

1. On the laptop, run:
   ```powershell
   cloudflared tunnel --url http://localhost:8000
   ```
2. Copy the generated URL (e.g., `https://xxxx.trycloudflare.com`).
3. On the other PC, start the agent with:
   ```cmd
   cafe-agent.exe -url https://xxxx.trycloudflare.com/api/v1/heartbeat -token <AGENT_TOKEN>
   ```
   *(This bypasses all local firewall and network configuration).*

---

## 9. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| **Heartbeat returns 401** | Agent token does not match hash | Regenerate token & hash (Step 2.1), update `AGENT_TOKEN_SHA256` in `deploy/.env`, and restart `web` container. |
| **Heartbeat returns 403** | Unknown PC rejected | Tick **Allow new PCs** in Admin → Café settings. |
| **Connection Refused / Timeout** | Firewall or wrong port binding | Verify port `8000:8000` in `docker-compose.yml` and add firewall inbound rule (Step 5.2). |
| **HTTP 400 Bad Request (DisallowedHost)** | Host header not allowed | Add `*` or laptop's IP to `DJANGO_ALLOWED_HOSTS` in `deploy/.env`. |
| **Docker Desktop paused error** | Docker engine is paused | Unpause Docker Desktop via system tray icon. |
