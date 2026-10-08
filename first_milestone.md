# Gaming Café MIS — Milestone 1: PC Status Monitoring

**Status:** Draft for review · **Date:** 2026-10-06

## 1. Goal

Show the live status of all 30 diskless gaming PCs on a simple web dashboard:

| State | Rule |
|---|---|
| **Off** | PC sent a shutdown message, or has been silent for more than 3 minutes |
| **In Use** | PC is on and had keyboard/mouse input within the idle threshold |
| **Idle** | PC is on and had no keyboard/mouse input for at least the idle threshold (default **10 min**, changeable from the dashboard admin without touching the PCs) |

**Hard constraint:** virtually zero extra load on the gaming PCs and on the CCBoot server. Gamers must not be able to notice any difference.

**Long-term context:** this is the first building block of a full café MIS (booking, payment gateway, user insights and analytics), which will be written mostly in Python. Milestone 1 lays down the foundation those modules build on: the PC registry, the status history, the backend framework, the database, and the hosting.

### 1.1 Known environment

- 30 diskless Windows PCs booted over the LAN by **CCBoot**.
- One CCBoot server that provides the disks (iSCSI). **It is not touched by this project.**
- No existing billing or session software; staff track time and payment manually.
- Café has an internet connection; the PCs can reach the internet (needed for online games anyway).

### 1.2 Assumptions to verify before build

1. PCs **auto-log on** to Windows after boot (normal for diskless cafés). The agent runs inside the logged-on session.
2. CCBoot assigns each client a **unique hostname** (e.g. `PC01`–`PC30`). The hostname is the PC's identity in the system.
3. Outbound HTTPS (TCP 443) from the PCs to the internet is allowed.
4. CCBoot "super client" (image upload) mode is available to install software into the shared image.

## 2. Design principles for near-zero impact

1. **Nothing on the CCBoot server, switches, DHCP or PXE.** The server feeds disk I/O to every PC; any load there is felt by all 30 gamers.
2. **The PC agent does one thing:** read a counter Windows already maintains (`GetLastInputInfo`) and report it. No keyboard/mouse hooks, no process scanning, no screenshots, no access to game memory. This also keeps it invisible to anti-cheat systems.
3. **Zero disk writes.** On a diskless PC every write goes to CCBoot's write-back cache on the server. The agent writes no logs, no temp files and no config.
4. **Lowest priority.** The agent runs in Windows background mode (low CPU, I/O and memory priority), single-threaded, and sleeps between heartbeats.
5. **Fixed, tiny, outbound-only traffic.** One ~200-byte HTTPS message per minute per PC. No inbound ports are opened anywhere.
6. **Smart server, dumb agent.** Thresholds, the heartbeat interval and an emergency off switch all live in the cloud. Tuning never requires touching the PC image.
7. **Measure, pilot, then roll out, with three levels of rollback** (see section 8).

## 3. Architecture

```
 Café LAN                                           Cloud (developer-owned)
┌───────────────────────────────┐                 ┌────────────────────────────────────┐
│ CCBoot server  (UNTOUCHED)    │                 │ Cloudflare (free)                  │
│                               │                 │  ├ DNS + HTTPS for your domain     │
│ PC01..PC30 (diskless Windows) │   HTTPS :443    │  ├ Tunnel (no open ports on VM)    │
│  └ cafe-agent.exe ────────────┼────────────────►│  └ Access (optional dashboard lock)│
│     1 msg/min, ~200 B         │  outbound only  │            │                       │
│                               │                 │            ▼ (tunnel)              │
│ Staff phone / laptop ─────────┼────────────────►│ Oracle Cloud Always Free VM        │
│     (browser)                 │                 │  Docker Compose:                   │
└───────────────────────────────┘                 │   ├ cloudflared   (tunnel client)  │
                                                  │   ├ web    Django + Gunicorn       │
                                                                                                    │   └ db     PostgreSQL              │
                                                  └────────────────────────────────────┘
```

### 3.1 Components

| # | Component | Runs on | Single responsibility |
|---|---|---|---|
| 1 | `cafe-agent.exe` | Each gaming PC | Report "seconds since last input" once a minute, plus boot and shutdown events |
| 2 | Heartbeat API | Cloud (Django view) | Authenticate, validate and store each heartbeat, record state changes with exact times; reply with the current interval and on/off switch |
| 3 | Dashboard | Cloud (Django page) | Show 30 tiles plus summary counts; refresh every 10 s |
| 4 | Admin | Cloud (Django admin) | PC list, settings (idle threshold, etc.), staff accounts |

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| PC agent | **Go** (current stable), single static `.exe` for Windows amd64 | ~6–10 MB RAM, no runtime to install into the image, starts instantly. Python is rejected for the agent: a PyInstaller exe unpacks itself to disk on every launch, and on diskless PCs that lands in the server's write-back cache. |
| Agent autostart | Windows **Task Scheduler** task "at log on of any user", defined in `task.xml` | Built into Windows, no service wrapper needed, and runs in the user session where input time is visible |
| Backend | **Python 3.12+ / Django 5.2 LTS** (or the latest LTS at build time), Gunicorn | The future MIS is mostly Python. Django's built-in admin, accounts and permissions, ORM and migrations give us the back office for free and suit booking, payments and reporting later. |
| Database | **PostgreSQL 17+** | One database for the whole MIS. Later it enables a database-enforced "no overlapping bookings" rule (an `EXCLUDE` constraint) and strong analytics SQL. |
| Hosting | **Oracle Cloud Always Free** VM (ARM, Ubuntu LTS), **Docker Compose** | ₹0/month and full CPython. Docker keeps it portable: moving to any paid host later is a copy, not a rewrite. |
| Edge | **Cloudflare** free plan: DNS, **Tunnel**, optional **Access** | HTTPS with no open inbound ports, no firewall or certificate management, optional extra login protection for the dashboard |
| Backups | Nightly `pg_dump` to **Cloudflare R2** (free tier) | Off-machine copies, no script beyond one cron line |
| Domain | Any registrar, managed in Cloudflare | Required by Cloudflare Tunnel. Payment gateways also typically require a business website during merchant onboarding. **The only paid item (~₹800–1,000/year).** |
| Source control & CI | GitHub (`KrishShah3011/Gaming_MIS`), GitHub Actions for tests and agent builds | Developer-owned |

### 4.1 Ownership and control

Every account is in the **developer's** name: Oracle Cloud, Cloudflare, the domain, GitHub. The café owner needs no cloud account and receives only a Django staff login, which the developer can revoke at any time.

| Role | Access |
|---|---|
| Developer | Django superuser, all cloud accounts, deploys, secrets |
| Café owner / staff | Dashboard, plus editing the idle threshold in admin. No access to infrastructure. |

Oracle account housekeeping (protects the free VM):
- Convert the account to **Pay-As-You-Go**. It stays ₹0 inside the Always Free limits, and it stops Oracle reclaiming the VM for looking idle (our workload is far below Oracle's 20% idle threshold).
- Set a **$1 budget alert** so any accidental charge is caught at once.
- Use only Always Free shapes.

## 5. PC agent (`cafe-agent.exe`)

### 5.1 Behaviour

1. **Start:** launched by Task Scheduler at logon, with no console window (built with `-H windowsgui`).
   - Immediately switches itself to background mode (`PROCESS_MODE_BACKGROUND_BEGIN`).
   - Waits a random 0–30 s, so 30 PCs powered on together don't report in the same second.
   - Sends a `boot` event.
2. **Loop:** every `interval` seconds (default 60), computes `idle_s = (GetTickCount() − LASTINPUTINFO.dwTime) / 1000` and sends a `heartbeat`.
   - Both values are 32-bit, so the subtraction stays correct when the counter wraps around.
3. **Shutdown:** a hidden top-level window receives `WM_QUERYENDSESSION` / `WM_ENDSESSION` and sends a `shutdown` event with a 2 s timeout.
   - It must be a top-level window: message-only windows do not receive these broadcasts.
4. **Server reply:** every response carries `{"interval": 60, "enabled": true}`.
   - The agent accepts an interval only between 30 and 3600 s.
   - `"enabled": false` makes the agent exit until the next boot. This is the remote off switch.
5. **Errors:** if a send fails, drop it and try again at the next tick. There is no queue, no retry storm and nothing written to disk. Only the latest status matters.

### 5.2 Message format

`POST https://status.<domain>/api/v1/heartbeat`
Header: `Authorization: Bearer <agent token>`

```json
{
  "pc": "PC07",
  "mac": "AA:BB:CC:DD:EE:FF",
  "event": "heartbeat",
  "idle_s": 132,
  "boot_id": "4f1c…",
  "uptime_s": 3600,
  "agent_version": "1.0.0"
}
```

- `event` is one of `boot`, `heartbeat` or `shutdown`.
- `boot_id` is random per agent start, so the server can tell one run from the next.
- The server URL and token are compiled into the exe at build time (Go `-ldflags`). The agent reads and writes no config file.
- HTTP keep-alive is used, so TLS setup isn't repeated every minute.

### 5.3 Resource budget (acceptance limits)

| Resource | Limit |
|---|---|
| CPU | ≤ 0.1% of one core, averaged over 1 h of gaming; nothing visible in frame-time traces |
| RAM (private working set) | ≤ 15 MB |
| Disk writes after startup | **0 bytes** |
| Network | ≤ 2 KB/min per PC, including TLS/HTTP overhead |
| Privileges | Standard user. No admin rights, no driver, no service, no hooks. |

### 5.4 Installation in the CCBoot image

- Install to `C:\Program Files\CafeAgent\cafe-agent.exe`.
- Register the scheduled task with `schtasks /Create /TN CafeAgent /XML task.xml`. The task runs for the built-in Users group, only while a user is logged on, with no time limit and at priority 7 (below normal).
- The exe (~5 MB) is read from the image once per boot. That is negligible next to a Windows boot, and CCBoot's server cache serves it.

## 6. Cloud backend (Django)

### 6.1 Data model

```
PC
  id, hostname (unique), mac, label, is_active,
  last_seen_at, last_event, idle_s_at_last_seen, boot_id, agent_version,
  state ∈ {off, in_use, idle}, state_since, created_at

StateChange                      ← history for future analytics; cannot be back-filled later
  id, pc → PC, from_state, to_state, at        (index: pc, at)

Settings (single row, editable in admin)
  idle_threshold_s      = 600
  offline_timeout_s     = 180
  heartbeat_interval_s  = 60
  agents_enabled        = true
```

Live status fields sit directly on `PC`, so there's no separate status table. Future modules (`Booking`, `Session`, `Payment`) will reference `PC`.

### 6.2 State rules

There is **no background job**. Every state follows from the last heartbeat plus the clock, so it is computed exactly when needed. The moment a PC *will* go Idle or Off is known in advance:

```
idle_at = last_seen_at − idle_s_at_last_seen + idle_threshold_s
off_at  = last_seen_at                       if last_event == "shutdown"
          last_seen_at + offline_timeout_s   otherwise
```

All rules live in `status/state.py` as **two pure functions**, which are easy to unit-test:

1. **`compute_state(pc, now, settings)`** gives the live state. The dashboard calls it on every page load, and it is read-only.
   ```
   if now ≥ off_at:     → off
   elif now ≥ idle_at:  → idle
   else:                → in_use
   ```
2. **`settle(pc, heartbeat, now, settings)`** gives the list of `(state, at)` transitions since the previous heartbeat, with **exact timestamps**. The heartbeat view calls it, then saves the rows to `StateChange` and the new live fields to `PC`.
   - The new heartbeat says when the last input happened (`now − idle_s`), so the history stays truthful.
   - Example: a PC that went Idle at `idle_at` and was picked up again at `now − idle_s` gets both rows.
   - Example: a PC that went silent and later boots gets `off` at `off_at`, then `in_use` at boot.

Rules that apply to both:
- Only the **server clock** is used. PC clocks are never trusted.
- History accuracy is limited by the heartbeat interval: of all the input between two heartbeats, the server only sees the last one.
- **Known edge case (dashboard only):** `compute_state` assumes there has been no input since the last heartbeat. A PC whose user touches the keyboard just before the threshold can briefly show **Idle** until its next heartbeat arrives (≤ 60 s). The history is not affected, because `settle` corrects it. This is accepted for Milestone 1.
- **Silent PCs:** the `off` row for a PC that goes silent is written when that PC next sends a heartbeat. Until then, the dashboard already shows it as Off. Milestone 4 analytics will settle any open periods before running reports.
- **Café-wide outage:** if no PC has reported for longer than `offline_timeout_s`, the dashboard shows a banner: *"No data from café for N min — internet may be down; statuses may be stale."* This way an internet outage isn't mistaken for everyone switching off.

### 6.3 Heartbeat endpoint

- Rejects a missing or wrong token with `401`. The token comparison is constant-time (`hmac.compare_digest`).
- Rejects anything malformed with `400`:
  - body larger than 1 KB
  - hostname not matching `^[A-Za-z0-9-]{1,32}$`
  - unknown `event`
  - `idle_s` outside 0 to 10⁷
- **Auto-registers** an unknown hostname as a new `PC` (label defaults to the hostname and can be renamed in admin), up to a hard cap of 50 PCs.
- Calls `settle`, writes the `StateChange` rows and live fields in one database transaction, and returns `{"interval", "enabled"}` from `Settings`.
- `shutdown` therefore shows as **Off immediately**.

### 6.4 Dashboard

- One Django page behind a login. A grid of 30 tiles, each showing:
  - the PC label
  - the **state written as text** as well as a colour (readable by colour-blind staff)
  - how long it has been in that state ("Idle 14 min", "Off since 18:02")
- Summary line at the top: `In use 21 · Idle 3 · Off 6`, plus the outage banner when relevant.
- Refreshes with `<meta http-equiv="refresh" content="10">`. No JavaScript framework and no websockets.
- Hosted on `app.<domain>`. It can additionally be put behind Cloudflare Access (free for up to 50 users).
- Heartbeats use the separate host `status.<domain>`, which is **not** behind Access and is protected by the agent token instead.

### 6.5 Security

- **Agent token:** one token for the whole café, compiled into the agent. Anyone who extracts it from the image can only send fake *status* data. It grants no access to the dashboard, admin or (later) payments.
  - Mitigations: strict validation, the 50-PC cap, a Cloudflare rate-limit rule on `/api/v1/heartbeat`, and token rotation through an image update.
- **Network exposure:** Postgres is never exposed; it is reachable only inside the Docker network. The VM has **no inbound ports open**: SSH goes through Cloudflare Tunnel, or is restricted to the developer's IP in Oracle's network rules.
- **Secrets** (Django `SECRET_KEY`, agent token hash, database password, R2 keys) live in a `.env` on the VM. Never commit them to git.
- **Patching:** `unattended-upgrades` applies OS security patches automatically.

### 6.6 Operations

| Task | How |
|---|---|
| Deploy | `git pull && docker compose up -d --build` on the VM (later via GitHub Actions) |
| Backups | Nightly `pg_dump` → R2, keep 14 days. Do one test restore before go-live. |
| Health | `GET /healthz` checked by a free uptime monitor, which alerts the developer by email |
| Restarts | Docker restart policy `unless-stopped` |

## 7. Network impact (café LAN)

- **Traffic:** 30 PCs × ~1 KB/min ≈ 0.5 kbit/s in total. A single online game uses roughly 50–200 kbit/s per PC. The agent's traffic sits well below anything the network or gamers could notice.
- **No changes** to switches, VLANs, DHCP, PXE or the CCBoot server. Only outbound TCP 443 is used.
- **Optional:** if the café router supports QoS, mark the agent's traffic as low priority (DSCP CS1) with a Windows QoS policy. That needs no code change, and at this volume it isn't needed.

## 8. Implementation and rollout procedure

### Phase 0: Prerequisites
1. Create the developer-owned accounts:
   - Oracle Cloud: convert to Pay-As-You-Go and add the $1 budget alert.
   - Cloudflare, with the domain added.
   - The GitHub repo.
2. Take an inventory of all PCs: hostname, MAC, CCBoot image used.
3. List the games played and the **anti-cheat** each uses (e.g. Vanguard, Easy Anti-Cheat, BattlEye, FACEIT, VAC).
4. Confirm assumptions 1–4 in section 1.2.

### Phase 1: Cloud side
1. Create the Django project `mis` and app `status`, and the Docker Compose stack. Build and test them on the developer's laptop first. The Oracle VM and named Cloudflare Tunnel come after the owner demo (Phase 2b).
2. Implement the models, `state.py` (`compute_state`, `settle`), the heartbeat view, the dashboard and admin.
3. Test end-to-end with **`tools/simulate_pcs.py`**: 30 fake PCs going boot → in use → idle → shutdown and silent → off, sent from the developer's laptop.

### Phase 2: Agent, and a benchmark on one PC (outside café hours)
1. Build `cafe-agent.exe`.
2. **Baseline without the agent** on one PC. Do 3 runs of each of the 3 most-played games:
   - average FPS, 1% low FPS and frame times, using PresentMon or CapFrameX
   - CPU and RAM use
   - in-game ping
3. **With the agent:** run the exe by hand. On a diskless PC this goes to the write-back cache and **disappears on reboot**, so it's a no-risk test. Repeat the same measurements.
4. Check the agent's own disk writes (Process Monitor) and its CPU and RAM (Process Explorer) against section 5.3.
5. Launch every anti-cheat game with the agent running, and confirm there are no kicks, warnings or Windows Defender alerts.

### Phase 2b: Prototype demo for the café owner (before any cloud spend)
1. Run the stack on the developer's laptop (Docker Desktop). Expose it with a temporary Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8000`). This needs no account and no domain.
2. At the café, run `cafe-agent.exe` by hand on 2–3 PCs. On a diskless PC it lives in the write-back cache and disappears on reboot. Simulated PCs fill the remaining tiles.
3. Show the owner the dashboard on their phone, with real PCs changing state, and the Phase 2 numbers showing no FPS impact.
4. With the owner's approval, deploy properly: Oracle VM, domain, named Tunnel (Phase 1 hosting). Then continue with Phase 3.

### Phase 3: Pilot in the image (2 PCs, 3 days)
1. **Back up the CCBoot image first.** Create a restore point or copy the image file.
2. In super-client mode, install the agent and the scheduled task (section 5.4) into a **copy** of the image. Assign that copy to 2 pilot PCs.
3. Run for 3 days of normal business. Check the dashboard against reality several times a day, and check the PCs against the resource budget.

### Phase 4: Full rollout
1. During closed hours, apply the change to the production image and reboot all PCs.
2. Watch the dashboard and collect gamer feedback for 1 week. Then sign off against section 9.

### Rollback (fastest first)
1. **Remote off switch:** set `agents_enabled = false` in admin. Every agent exits within one heartbeat interval. No image change and no reboot needed.
2. **Disable the scheduled task** in the image (super-client mode).
3. **Restore the image backup** taken in Phase 3 and reboot the PCs.

## 9. Acceptance criteria

**Gamer experience**
- [ ] Average FPS and 1% lows with the agent are within run-to-run noise (< 2% difference) of the baseline, in all 3 benchmark games.
- [ ] Agent stays within every limit in section 5.3.
- [ ] Zero anti-cheat or antivirus incidents during the pilot and the rollout week.
- [ ] Nothing installed or changed on the CCBoot server or network equipment.

**Status accuracy** (measured with the dashboard open)

| Event | Shows on the dashboard within |
|---|---|
| Normal Windows shutdown → **Off** | ≤ 15 s |
| Power cut / hard power-off → **Off** | ≤ 3 min 10 s (timeout + one refresh) |
| Last input → **Idle** | ≤ threshold + 10 s (one dashboard refresh) |
| Input resumes → **In Use** | ≤ 70 s (one heartbeat + one refresh) |
| Café internet down | Outage banner shown, with no false mass "Off" |

**Operations**
- [ ] Idle threshold changed in admin takes effect without touching any PC.
- [ ] Remote off switch tested: agents exit and the dashboard shows them silent.
- [ ] Database backup restored successfully once.
- [ ] Cloud running cost ₹0/month (domain excepted).

## 10. Testing strategy

| What | How |
|---|---|
| `compute_state` | Django unit tests covering every rule and boundary (exactly at the threshold, at the timeout, shutdown taking priority) |
| Heartbeat view | Tests for bad token → 401, malformed body → 400, auto-register, the 50-PC cap, shutdown → Off immediately, and the reply carrying interval/enabled |
| `settle` | Table tests for every transition sequence: in use → idle → in use between heartbeats, silence → off → boot, shutdown → boot, threshold exactly reached; each transition written once, with its exact time |
| Agent | Go unit test for the idle calculation, including counter wrap. Everything else is checked by the Phase 2 benchmark on real hardware. |
| End-to-end | `tools/simulate_pcs.py` (30 virtual PCs) against the deployed stack |

## 11. Repository layout

```
Gaming_MIS/
├── first_milestone.md
├── agent/                     # Go — runs on gaming PCs
│   ├── main.go
│   ├── idle_test.go
│   ├── task.xml               # Task Scheduler definition
│   └── go.mod
├── server/                    # Django — the MIS backend
│   ├── manage.py
│   ├── mis/                   # project: settings, urls
│   ├── status/                # Milestone 1 app: models, state.py, views, templates, tests
│   ├── requirements.txt
│   └── Dockerfile
├── deploy/
│   ├── docker-compose.yml     # web, db, cloudflared
│   └── backup.sh              # pg_dump → R2
└── tools/
    └── simulate_pcs.py
```

Future milestones add Django apps next to `status/` (`booking/`, `payments/`, `analytics/`) in the same project and database.

## 12. Out of scope for Milestone 1

- Customer accounts, sessions, booking, payments, analytics screens (later milestones)
- Remote actions on PCs (shutdown, lock, messages). The agent is **report-only** by design.
- Multi-café support, mobile app, real-time push (websockets), alerts and notifications
- Reading CCBoot's internal data (possible later, as "Approach 3", if Off accuracy needs to be better)

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Anti-cheat flags an unsigned exe | Phase 2 test on every anti-cheat title. If anything is flagged, buy a code-signing certificate. |
| PC logs off without shutting down → shows Off while powered on | Rare in auto-logon cafés; accepted for Milestone 1. Verify assumption 1. |
| Oracle changes its free-tier terms or reclaims the VM | Pay-As-You-Go conversion, budget alert, nightly off-site backups. The Docker stack moves to any host in under an hour. |
| Café internet outage | Outage banner and a gap in history. PC gaming itself is unaffected. |
| Agent token extracted from the image | It only allows fake status data. Strict validation, rate limit, 50-PC cap, rotate if abused. |
| Idle → In Use shows up to ~70 s late | Acceptable for a status board. If needed later, the agent can check input locally every 5 s and send an early heartbeat. |

## 14. Path to the full MIS (indicative)

| Milestone | Builds on Milestone 1 |
|---|---|
| M2: Sessions & booking | `Session` and `Booking` reference `PC`. A Postgres `EXCLUDE` constraint blocks overlapping bookings. An active session adds the "customer present / seat free" dimension to the status board. |
| M3: Payments | Gateway webhooks reach `app.<domain>` through the existing Tunnel. Move Postgres to a managed database with point-in-time recovery once real money is involved. |
| M4: Insights & analytics | `StateChange` history (collected from day one of Milestone 1) gives utilisation per PC and per hour, and peak times, combined with booking and payment data |
