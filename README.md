# Gaming Café PC Status — Milestone 1 prototype

Shows whether each PC in a gaming café is **In Use**, **Idle** or **Off** on a live web dashboard.

- `agent/` — a tiny Go program that runs on each Windows PC and sends a heartbeat (seconds since last keyboard/mouse/controller input) every minute. No disk writes, background priority, ~0% CPU.
- `server/` — Django + PostgreSQL. Receives heartbeats, works out each PC's state, serves the staff dashboard and admin.
- `deploy/` — Docker Compose for the server.
- `tools/simulate_pcs.py` — pretends to be up to 29 PCs so you can test without a café.

Full design: [`first_milestone.md`](first_milestone.md).

This guide walks you through running it on your own computer and checking every part works.

---

## 1. What you need

| Tool | Needed for | Get it |
|---|---|---|
| Git | cloning the repo | https://git-scm.com |
| Docker Desktop | running the server | https://www.docker.com/products/docker-desktop |
| Python 3.10+ | the PC simulator and generating secrets | https://www.python.org |
| Go 1.22+ (Windows only) | building the real agent (optional) | https://go.dev/dl |
| cloudflared (optional) | sharing the dashboard over the internet | https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ |

Make sure Docker Desktop is running (not paused) before you start.

## 2. Set up

```bash
git clone https://github.com/KrishShah3011/Gaming_MIS.git
cd Gaming_MIS
cp deploy/.env.example deploy/.env
```

Generate two secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
python -c "import secrets, hashlib; t = secrets.token_urlsafe(32); print('TOKEN (give to agents):', t); print('AGENT_TOKEN_SHA256=' + hashlib.sha256(t.encode()).hexdigest())"
```

Open `deploy/.env` and fill in:

- `DJANGO_SECRET_KEY` = the first output
- `POSTGRES_PASSWORD` = any password you like
- `AGENT_TOKEN_SHA256` = the hash from the second output

**Keep the TOKEN** from the second output somewhere — the simulator and agent need it. Never commit `deploy/.env`.

## 3. Start the server

```bash
cd deploy
docker compose up -d --build
docker compose ps
```

**Expect:** `db` shows `healthy`, `web` shows `running`.

```bash
curl http://localhost:8000/healthz
```

**Expect:** `ok`

Create your admin login:

```bash
docker compose exec web python manage.py createsuperuser
```

## 4. Run the automated tests

```bash
docker compose run --rm web python manage.py test status
```

**Expect:** `Ran 47 tests ... OK`

If you have Go installed:

```bash
cd ../agent
go test ./...
cd ../deploy
```

**Expect:** `ok  cafe-agent`

## 5. Check the dashboard and login

1. Open http://localhost:8000 — **expect** to be sent to the login page.
2. Log in with the admin user from step 3 — **expect** the dashboard (empty, no PCs yet).
3. Open http://localhost:8000/accounts/password_reset/ — **expect** a 404 page (only login/logout are exposed).

## 6. Use short timings for testing

The real defaults wait 10 minutes before calling a PC idle. For testing, open http://localhost:8000/admin/ → **Café settings** and set:

| Field | Test value | Real default |
|---|---|---|
| Idle threshold (s) | 60 | 600 |
| Heartbeat interval (s) | 30 | 60 |
| Offline timeout (s) | 60 | 180 |
| Allow new PCs | ticked | unticked after setup |

Save. "Allow new PCs" must be ticked or unknown PCs are refused (403).

## 7. Simulate 29 PCs

From the repo root:

```bash
python tools/simulate_pcs.py --token YOUR_TOKEN --interval 30
```

**Expect:**

- Within ~30 s, tiles PC02–PC30 appear on the dashboard, a mix of **In Use** and **Idle**.
- The dashboard updates by itself every 10 s without flashing or jumping.
- The counts at the top (In use / Idle / Off) add up.

Then press **Ctrl+C** to stop the simulator. **Expect:** about 60 s later all tiles turn **Off** and a yellow banner says *"No data from the café for N min — internet may be down"*. (Every PC going silent at once without a shutdown message looks like an internet outage. The banner disappears as soon as heartbeats return.)

Extra checks:

- Run the simulator with a wrong token (`--token wrong`) — **expect** it to print `401` responses and no tiles to change.
- Stop the server (`docker compose stop web`, from `deploy/`) while the simulator runs — **expect** `unreachable (...)` messages, no crash. Start it again with `docker compose start web`.

## 8. Test the real agent (Windows only)

Build it:

```bash
cd agent
go build -trimpath -ldflags "-H windowsgui -s -w -X main.version=0.1.0" -o cafe-agent.exe .
```

Run it (it has no window — look for `cafe-agent.exe` in Task Manager → Details):

```bash
./cafe-agent.exe -url http://localhost:8000/api/v1/heartbeat -token YOUR_TOKEN
```

The agent waits a random 0–30 s before its first heartbeat, then a tile with your computer's name appears.

| Do this | Expect on the dashboard |
|---|---|
| Use mouse/keyboard normally | Your tile shows **In Use** |
| Leave the computer untouched for over 60 s | **Idle** |
| Move the mouse | Back to **In Use** within ~30 s |
| Play using only an Xbox-compatible controller (if you have one) | Stays **In Use** |
| End `cafe-agent.exe` in Task Manager | **Off** about 60 s later |
| Start the agent again, then sign out or shut down Windows | **Off** immediately |
| Untick **Agents enabled** in Café settings | The agent exits by itself at its next heartbeat |

**Load check:** in Task Manager → Details, `cafe-agent.exe` should show 0% CPU and only a few MB of memory.

## 9. Share the dashboard over the internet (optional)

```bash
cloudflared tunnel --url http://localhost:8000
```

Open the printed `https://....trycloudflare.com` link on a phone, log in, and **expect** the same dashboard. The link changes every time you run the command.

## 10. Clean up

```bash
cd deploy
docker compose down        # stop the server, keep data
docker compose down -v     # stop the server and delete all data
```

---

## Checklist

- [ ] `healthz` returns `ok`
- [ ] 47 Django tests pass (and Go tests, if Go installed)
- [ ] Dashboard requires login; password reset page is 404
- [ ] Simulated PCs appear, show In Use / Idle, and go Off (with the outage banner) after stopping
- [ ] Wrong token is rejected
- [ ] Simulator survives the server going down
- [ ] Real agent: In Use → Idle → In Use → Off works
- [ ] Agent uses ~0% CPU
- [ ] Dashboard works through the Cloudflare link

## Troubleshooting

| Problem | Fix |
|---|---|
| `docker compose` errors about the daemon | Start (or unpause) Docker Desktop |
| `KeyError: 'DJANGO_SECRET_KEY'` | `deploy/.env` is missing or empty — redo step 2 |
| Every heartbeat gets `401` | `AGENT_TOKEN_SHA256` doesn't match the token; regenerate both, then `docker compose up -d --force-recreate web` |
| New PCs get `403` | Tick **Allow new PCs** in Café settings |
| Can't stay logged in on Safari at `http://localhost` | Set `DJANGO_SECURE_COOKIES=0` in `deploy/.env` and recreate `web` |
| CSRF error when logging in through the tunnel | Make sure you use the `https://` link, not `http://` |
