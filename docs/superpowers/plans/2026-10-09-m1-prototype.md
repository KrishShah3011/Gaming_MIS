# Milestone 1 Prototype (Laptop + Owner Demo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working PC-status prototype on the developer's laptop: a Django dashboard showing In Use / Idle / Off, fed by a real Go agent and 29 simulated PCs, ready to demo on real café PCs through a temporary Cloudflare quick tunnel.

**Architecture:** A Django app (`status`) inside project `mis` stores one row per PC and a history of state changes in PostgreSQL. Two pure functions in `status/state.py` hold every state rule: `compute_state` (live state, used by the dashboard) and `settle` (state changes with exact timestamps, used when a heartbeat arrives). There are no background jobs. A single-file Go agent posts a heartbeat every 60 s. `tools/simulate_pcs.py` fakes the other PCs. Everything runs in Docker Compose (`web` and `db`).

**Tech Stack:** Python 3.12, Django 5.2 LTS, psycopg 3, gunicorn, WhiteNoise, PostgreSQL 17, Docker Compose, Go 1.27 (standard library only), cloudflared (quick tunnel for the demo only).

**Spec:** `first_milestone.md` (approved). This plan covers its Phase 1 (cloud side, built on the laptop), Phase 2 (agent and benchmark) and Phase 2b (owner demo).
**Out of scope** (later plan): Oracle VM, domain, named Cloudflare Tunnel and Access, backups, installing into the CCBoot image (§5.4 / Phase 3), and compiling the token into the exe.

**Branch:** before Task 1, run `git switch -c m1-prototype` from the repo root.

## Global Constraints

- Agent: Go, standard library only, single `.exe` for Windows amd64. No hooks, no process scanning, no disk writes, background mode (spec §2, §5).
- Agent idle time = time since the latest keyboard, mouse **or XInput controller** input. Controllers are polled every 5 s; empty slots once a minute; Microsoft deadzones 7849 (left stick), 8689 (right stick), 30 (triggers) (spec §5.1).
- Shutdown is detected with a hidden top-level window (`WM_ENDSESSION`), not `SetConsoleCtrlHandler`. The shutdown message reuses the open connection, with a 2 s timeout (spec §5.1).
- Agent budget: CPU ≤ 0.1% of one core; RAM ≤ 15 MB private working set; 0 bytes of disk writes after startup; ≤ 2 KB/min of network (spec §5.3).
- Heartbeat every 60 s by default. The agent clamps the server's interval to 30–3600 s. `"enabled": false` makes the agent exit until the next boot (spec §5.1).
- `POST /api/v1/heartbeat` with `Authorization: Bearer <token>`. Body ≤ 1 KB; hostname `^[A-Za-z0-9-]{1,32}$`; event ∈ `boot|heartbeat|shutdown`; `idle_s` 0–10⁷; at most 50 PCs; token compared in constant time. Unknown hostnames get 403 unless `allow_new_pcs` is ticked (spec §6.3).
- Defaults: `idle_threshold_s=600`, `offline_timeout_s=180`, `heartbeat_interval_s=60`, `agents_enabled=True`, `allow_new_pcs=False` (spec §6.1).
- Only the server clock is used. No background jobs (spec §6.2).
- Python 3.12+, Django 5.2 LTS, PostgreSQL 17, Docker Compose (spec §4).
- Dashboard: state shown as text and colour; refreshed every 10 s by a small plain-JavaScript fetch that swaps only the summary, banner and grid, with `<noscript><meta http-equiv="refresh" content="10"></noscript>` as the fallback; no HTMX or other JavaScript library; login required (spec §6.4).
- Secrets live only in `deploy/.env` and never in git (spec §6.5).

## Review Focus

1. **The same PC reports `pc07` one time and `PC07` the next** (Windows names are case-insensitive). It must stay one PC, not two. Pinned by Task 5: `test_hostname_is_case_insensitive`.
2. **A player uses only a controller** (FIFA, Rocket League). Windows' input counter ignores controllers, so the PC must still read In Use. Equally, stick drift on a controller nobody is touching must not keep it In Use forever. Pinned by Task 7: `TestPadActive`, `TestGamepadsTrackInput`, `TestIdleNowUsesControllerInput`.
3. **Admin lowers the idle threshold while PCs are running.** The history must never record a change dated before the PC's last heartbeat. Pinned by Task 3: `test_threshold_lowered_never_backdates_before_last_heartbeat`.
4. **Owner logs in on the phone through the `https://….trycloudflare.com` link.** Login must not fail with a CSRF 403. Pinned by Task 6: `test_login_through_quick_tunnel_passes_csrf`.
5. **`AGENT_TOKEN_SHA256` left empty in `.env`.** Every heartbeat must be rejected (fail closed), never accepted. Pinned by Task 5: `test_empty_configured_token_rejects_everything`.

---

## File Structure

```
.gitignore                         # + *.exe
deploy/
  docker-compose.yml               # db (postgres:17) + web (Django/gunicorn)
  .env.example                     # every setting the stack reads; copy to .env
server/
  requirements.txt
  Dockerfile
  manage.py
  mis/                             # Django project: settings, urls, wsgi
    __init__.py  settings.py  urls.py  wsgi.py
  status/                          # Milestone 1 app
    __init__.py  apps.py
    state.py                       # pure state rules: compute_state, settle (no Django imports)
    models.py                      # CafeSettings, PC, StateChange
    admin.py
    views.py                       # healthz, heartbeat, dashboard
    urls.py
    migrations/                    # generated
    templates/status/dashboard.html
    templates/registration/login.html
    tests/
      __init__.py  test_health.py  test_state.py  test_models.py  test_heartbeat.py  test_dashboard.py
agent/
  go.mod
  main.go                          # the whole agent
  main_test.go
tools/
  simulate_pcs.py                  # fakes PC02..PC30
docs/benchmark-results.md          # filled in by hand at the café (Task 10)
```

**How commands are run.** The shell is Git Bash on Windows.
- **Django commands** run inside Docker, from `deploy/`. For example: `docker compose run --rm web python manage.py test status`.
- **Go commands** run from `agent/`. Open a *new* terminal after installing Go, so `go` is on the PATH.
- **Interactive commands** such as `createsuperuser` should be run from **PowerShell**. Git Bash's terminal can fail with "the input device is not a TTY".

---

### Task 1: Django skeleton, Docker stack, health check

**Files:**
- Create: `server/requirements.txt`, `server/Dockerfile`, `server/manage.py`, `server/mis/__init__.py`, `server/mis/settings.py`, `server/mis/urls.py`, `server/mis/wsgi.py`, `server/status/__init__.py`, `server/status/apps.py`, `server/status/urls.py`, `server/status/views.py`, `server/status/tests/__init__.py`, `server/status/tests/test_health.py`, `deploy/docker-compose.yml`, `deploy/.env.example`

**Interfaces:**
- Produces:
  - `GET /healthz` returns `200 "ok"`.
  - `settings.AGENT_TOKEN_SHA256` (str).
  - The URL include `status.urls` mounted at `/`.
  - Auth URLs at `/accounts/` (`login`, `logout`).

- [ ] **Step 1: Create the project files**

`server/requirements.txt`:
```
Django~=5.2.0
psycopg[binary]~=3.2
gunicorn~=23.0
whitenoise~=6.7
```

`server/Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "mis.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
```

`server/manage.py`:
```python
#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mis.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

`server/mis/__init__.py` and `server/status/__init__.py` and `server/status/tests/__init__.py`: empty files.

`server/mis/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mis.settings")
application = get_wsgi_application()
```

`server/mis/settings.py`:
```python
"""Settings come from environment variables (deploy/.env). See deploy/.env.example."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# SHA-256 hex digest of the agents' bearer token. Empty means every heartbeat is rejected.
AGENT_TOKEN_SHA256 = os.environ.get("AGENT_TOKEN_SHA256", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "status",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mis.urls"
WSGI_APPLICATION = "mis.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "mis"),
        "USER": os.environ.get("POSTGRES_USER", "mis"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# ponytail: WhiteNoise serves admin CSS straight from the installed apps, so no collectstatic step.
# Switch to STATIC_ROOT + collectstatic for the production deploy.
WHITENOISE_USE_FINDERS = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
```

`server/mis/urls.py`:
```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("status.urls")),
]
```

`server/status/apps.py`:
```python
from django.apps import AppConfig


class StatusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "status"
```

`server/status/urls.py` (no routes yet):
```python
urlpatterns = []
```

`server/status/views.py`: empty file for now.

`deploy/docker-compose.yml`:
```yaml
# Laptop prototype. The ../server mount + --reload means code edits apply without a rebuild.
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: mis
      POSTGRES_USER: mis
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mis -d mis"]
      interval: 5s
      retries: 10
    restart: unless-stopped

  web:
    build: ../server
    env_file: .env
    environment:
      POSTGRES_HOST: db
    command: >
      sh -c "python manage.py migrate --noinput &&
             gunicorn mis.wsgi --bind 0.0.0.0:8000 --workers 2 --reload --access-logfile -"
    volumes:
      - ../server:/app
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
```

`deploy/.env.example`:
```
# Copy to deploy/.env (never commit .env) and fill in.
# Secret key:  python -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.trycloudflare.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com
POSTGRES_PASSWORD=change-me
# Agent token: python -c "import secrets, hashlib; t = secrets.token_urlsafe(32); print('TOKEN (give to agents):', t); print('AGENT_TOKEN_SHA256=' + hashlib.sha256(t.encode()).hexdigest())"
AGENT_TOKEN_SHA256=
TIME_ZONE=Asia/Kolkata
```

- [ ] **Step 2: Create `deploy/.env` and build**

```bash
cd deploy
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"
```
Paste the output as `DJANGO_SECRET_KEY` in `deploy/.env`. Set `POSTGRES_PASSWORD` to any long random string. Leave `AGENT_TOKEN_SHA256` empty for now. Set `TIME_ZONE` to the café's time zone.

Run: `docker compose build`
Expected: the build ends with `Image deploy-web Built` (exact wording varies) and no errors.

- [ ] **Step 3: Write the failing test**

`server/status/tests/test_health.py`:
```python
from django.test import SimpleTestCase


class HealthTests(SimpleTestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
```

- [ ] **Step 4: Run it and confirm it fails**

Run (from `deploy/`): `docker compose run --rm web python manage.py test status`
Expected: `FAIL: test_healthz_returns_ok` with `AssertionError: 404 != 200`.

- [ ] **Step 5: Implement**

`server/status/views.py`:
```python
from django.http import HttpResponse


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
```

`server/status/urls.py`:
```python
from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
]
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status`
Expected: `Ran 1 test` … `OK`.

- [ ] **Step 7: Check the running stack**

Run: `docker compose up -d && sleep 5 && curl -s http://localhost:8000/healthz`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
cd ..
git add server deploy/docker-compose.yml deploy/.env.example
git status --short   # deploy/.env must NOT be listed
git commit -m "feat: Django skeleton, Docker stack and /healthz"
```

---

### Task 2: `compute_state`, the live-state rule

**Files:**
- Create: `server/status/state.py`
- Test: `server/status/tests/test_state.py`

**Interfaces:**
- Produces (`status/state.py`):
  - The constants `OFF = "off"`, `IN_USE = "in_use"`, `IDLE = "idle"`.
  - `@dataclass(frozen=True) class Last(seen_at: datetime | None, event: str, idle_s: int, state: str, since: datetime | None)`
  - `idle_at(last: Last, idle_threshold_s: int) -> datetime`
  - `off_at(last: Last, offline_timeout_s: int) -> datetime`
  - `compute_state(last: Last, now: datetime, idle_threshold_s: int, offline_timeout_s: int) -> tuple[str, datetime | None]`, which returns `(state, since)`.

- [ ] **Step 1: Write the failing tests**

`server/status/tests/test_state.py`:
```python
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from status.state import IDLE, IN_USE, OFF, Last, compute_state

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
THR, TIMEOUT = 600, 180


def s(seconds):
    return timedelta(seconds=seconds)


def last(state=IN_USE, idle_s=0, event="heartbeat", since=T0):
    """What the server knew after a heartbeat received at T0."""
    return Last(seen_at=T0, event=event, idle_s=idle_s, state=state, since=since)


NEVER_SEEN = Last(seen_at=None, event="", idle_s=0, state=OFF, since=None)


class ComputeStateTests(SimpleTestCase):
    def test_never_seen_is_off(self):
        self.assertEqual(compute_state(NEVER_SEEN, T0, THR, TIMEOUT), (OFF, None))

    def test_shutdown_is_off_immediately(self):
        self.assertEqual(compute_state(last(event="shutdown"), T0, THR, TIMEOUT), (OFF, T0))

    def test_off_exactly_at_timeout(self):
        self.assertEqual(compute_state(last(), T0 + s(180), THR, TIMEOUT), (OFF, T0 + s(180)))

    def test_not_off_one_second_before_timeout(self):
        self.assertEqual(compute_state(last(), T0 + s(179), THR, TIMEOUT)[0], IN_USE)

    def test_idle_exactly_at_threshold(self):
        self.assertEqual(compute_state(last(idle_s=540), T0 + s(60), THR, TIMEOUT), (IDLE, T0 + s(60)))

    def test_in_use_one_second_before_threshold(self):
        self.assertEqual(compute_state(last(idle_s=540), T0 + s(59), THR, TIMEOUT)[0], IN_USE)

    def test_idle_is_extrapolated_between_heartbeats(self):
        self.assertEqual(compute_state(last(idle_s=590), T0 + s(10), THR, TIMEOUT), (IDLE, T0 + s(10)))

    def test_unchanged_state_keeps_stored_since(self):
        earlier = T0 - s(900)
        result = compute_state(last(state=IDLE, idle_s=700, since=earlier), T0 + s(5), THR, TIMEOUT)
        self.assertEqual(result, (IDLE, earlier))

    def test_in_use_keeps_stored_since(self):
        earlier = T0 - s(300)
        result = compute_state(last(idle_s=3, since=earlier), T0 + s(30), THR, TIMEOUT)
        self.assertEqual(result, (IN_USE, earlier))
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `docker compose run --rm web python manage.py test status.tests.test_state`
Expected: `ModuleNotFoundError: No module named 'status.state'`.

- [ ] **Step 3: Implement**

`server/status/state.py`:
```python
"""PC state rules (first_milestone.md §6.2). Pure functions, no Django: easy to test.

Every state follows from the last heartbeat plus the clock, so there is no background job.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

OFF, IN_USE, IDLE = "off", "in_use", "idle"


@dataclass(frozen=True)
class Last:
    """What the server knew about a PC after its most recent heartbeat."""

    seen_at: datetime | None  # None = never reported
    event: str  # "boot" | "heartbeat" | "shutdown" | ""
    idle_s: int  # seconds since last input, as reported at seen_at
    state: str  # state stored at seen_at
    since: datetime | None  # when the stored state began


def idle_at(last: Last, idle_threshold_s: int) -> datetime:
    """When the PC goes (or went) Idle if nobody touches it."""
    return last.seen_at - timedelta(seconds=last.idle_s) + timedelta(seconds=idle_threshold_s)


def off_at(last: Last, offline_timeout_s: int) -> datetime:
    """When the PC counts as Off: at once after a shutdown, else after the silence timeout."""
    if last.event == "shutdown":
        return last.seen_at
    return last.seen_at + timedelta(seconds=offline_timeout_s)


def compute_state(last: Last, now: datetime, idle_threshold_s: int, offline_timeout_s: int):
    """Live (state, since) at `now`. Read-only; the dashboard calls it on every load."""
    if last.seen_at is None:
        return OFF, None
    went_off = off_at(last, offline_timeout_s)
    if now >= went_off:
        return OFF, last.since if last.state == OFF else went_off
    went_idle = idle_at(last, idle_threshold_s)
    if now >= went_idle:
        return IDLE, last.since if last.state == IDLE else went_idle
    return IN_USE, last.since if last.state == IN_USE else last.seen_at
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status.tests.test_state`
Expected: `Ran 9 tests` … `OK`.

- [ ] **Step 5: Commit**

```bash
git add server/status/state.py server/status/tests/test_state.py
git commit -m "feat: compute_state live PC state rule"
```

---

### Task 3: `settle`, the history of state changes with exact times

**Files:**
- Modify: `server/status/state.py` (append `settle`)
- Test: `server/status/tests/test_state.py` (append `SettleTests`)

**Interfaces:**
- Consumes: `Last`, `idle_at`, `off_at` and the constants from Task 2.
- Produces: `settle(last: Last, event: str, idle_s: int, now: datetime, idle_threshold_s: int, offline_timeout_s: int) -> list[tuple[str, datetime]]`.
  - It returns the real state changes since the previous heartbeat, oldest first.
  - The list never repeats the current state, and no timestamp falls before `last.seen_at`.
  - The caller takes the last element, if there is one, as the new `(state, since)`.

- [ ] **Step 1: Write the failing tests**

Append to `server/status/tests/test_state.py`. Also change the import line at the top to `from status.state import IDLE, IN_USE, OFF, Last, compute_state, settle`.
```python
class SettleTests(SimpleTestCase):
    def settle(self, last_, event, idle_s, after, thr=THR):
        return settle(last_, event, idle_s, T0 + s(after), thr, TIMEOUT)

    def test_first_heartbeat_turns_on(self):
        self.assertEqual(settle(NEVER_SEEN, "boot", 0, T0, THR, TIMEOUT), [(IN_USE, T0)])

    def test_steady_use_records_nothing(self):
        self.assertEqual(self.settle(last(idle_s=5), "heartbeat", 3, after=60), [])

    def test_goes_idle_between_heartbeats_at_exact_time(self):
        self.assertEqual(self.settle(last(idle_s=590), "heartbeat", 650, after=60), [(IDLE, T0 + s(10))])

    def test_idle_exactly_at_threshold(self):
        self.assertEqual(self.settle(last(idle_s=540), "heartbeat", 600, after=60), [(IDLE, T0 + s(60))])

    def test_idle_pc_picked_up_again(self):
        idle = last(state=IDLE, idle_s=700, since=T0 - s(100))
        self.assertEqual(self.settle(idle, "heartbeat", 20, after=60), [(IN_USE, T0 + s(40))])

    def test_idle_and_back_between_two_heartbeats(self):
        self.assertEqual(
            self.settle(last(idle_s=590), "heartbeat", 30, after=60),
            [(IDLE, T0 + s(10)), (IN_USE, T0 + s(30))],
        )

    def test_silence_then_boot(self):
        self.assertEqual(
            self.settle(last(idle_s=5), "boot", 2, after=600),
            [(OFF, T0 + s(180)), (IN_USE, T0 + s(600))],
        )

    def test_went_idle_before_going_silent(self):
        self.assertEqual(
            self.settle(last(idle_s=500), "boot", 2, after=900),
            [(IDLE, T0 + s(100)), (OFF, T0 + s(180)), (IN_USE, T0 + s(900))],
        )

    def test_back_on_but_nobody_there_is_idle(self):
        self.assertEqual(
            self.settle(last(idle_s=5), "heartbeat", 700, after=900),
            [(OFF, T0 + s(180)), (IDLE, T0 + s(900))],
        )

    def test_shutdown_message_is_off_now(self):
        self.assertEqual(self.settle(last(idle_s=5), "shutdown", 0, after=60), [(OFF, T0 + s(60))])

    def test_idle_then_shutdown(self):
        self.assertEqual(
            self.settle(last(idle_s=590), "shutdown", 650, after=60),
            [(IDLE, T0 + s(10)), (OFF, T0 + s(60))],
        )

    def test_boot_after_shutdown_records_only_the_boot(self):
        shut = last(state=OFF, idle_s=700, event="shutdown")
        self.assertEqual(self.settle(shut, "boot", 1, after=300), [(IN_USE, T0 + s(300))])

    def test_shutdown_after_long_silence(self):
        self.assertEqual(self.settle(last(idle_s=5), "shutdown", 10, after=600), [(OFF, T0 + s(180))])

    def test_threshold_lowered_never_backdates_before_last_heartbeat(self):
        # At T0 the PC was in use with 300 s idle (threshold was 600). Admin then lowers it to 120.
        self.assertEqual(self.settle(last(idle_s=300), "heartbeat", 360, after=60, thr=120), [(IDLE, T0)])
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `docker compose run --rm web python manage.py test status.tests.test_state`
Expected: `ImportError: cannot import name 'settle' from 'status.state'`.

- [ ] **Step 3: Implement**

Append to `server/status/state.py`:
```python


def settle(last: Last, event: str, idle_s: int, now: datetime, idle_threshold_s: int, offline_timeout_s: int):
    """State changes since the previous heartbeat, with exact times, oldest first.

    The new heartbeat tells us when the last input happened (now - idle_s), which lets
    us write history that the dashboard could only guess at. Accuracy is limited by the
    heartbeat interval: of all input between two heartbeats, only the last is visible.
    """
    last_input = now - timedelta(seconds=idle_s)
    timeline = []
    back_on = last.seen_at is None
    if not back_on:
        went_idle = idle_at(last, idle_threshold_s)
        went_off = off_at(last, offline_timeout_s)
        if now >= went_off:  # shut down, or silent too long: it was off in between
            if last.event != "shutdown" and went_idle < went_off:
                timeline.append((IDLE, went_idle))
            timeline.append((OFF, went_off))
            back_on = True
        elif went_idle < last_input:  # went idle, then someone touched it again
            timeline += [(IDLE, went_idle), (IN_USE, last_input)]

    if back_on:
        if event != "shutdown":
            timeline.append((IDLE if idle_s >= idle_threshold_s else IN_USE, now))
    elif now >= last_input + timedelta(seconds=idle_threshold_s):
        timeline.append((IDLE, last_input + timedelta(seconds=idle_threshold_s)))
    else:
        timeline.append((IN_USE, last_input))
    if event == "shutdown":
        timeline.append((OFF, now))

    changes, current, floor = [], last.state, last.seen_at or now
    for state, at in timeline:
        at = max(at, floor)  # never before the last heartbeat (e.g. threshold lowered mid-way)
        if state != current:
            changes.append((state, at))
            current, floor = state, at
    return changes
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status.tests.test_state`
Expected: `Ran 23 tests` … `OK`.

- [ ] **Step 5: Commit**

```bash
git add server/status/state.py server/status/tests/test_state.py
git commit -m "feat: settle writes state history with exact times"
```

---

### Task 4: Models and admin

**Files:**
- Create: `server/status/models.py`, `server/status/admin.py`, `server/status/migrations/0001_initial.py` (generated)
- Test: `server/status/tests/test_models.py`

**Interfaces:**
- Consumes: `Last`, `OFF`, `IN_USE`, `IDLE` from `status.state`.
- Produces:
  - `CafeSettings.load() -> CafeSettings`, a singleton (pk=1) with the fields `idle_threshold_s`, `offline_timeout_s`, `heartbeat_interval_s`, `agents_enabled` and `allow_new_pcs`.
  - `PC`, with the fields `hostname` (unique), `label`, `mac`, `is_active`, `last_seen_at`, `last_event`, `idle_s_at_last_seen`, `boot_id`, `agent_version`, `state`, `state_since` and `created_at`.
  - `PC.STATES`: a list of `(value, label)` pairs.
  - `PC.last() -> Last`.
  - `StateChange(pc, from_state, to_state, at)`, reachable as `pc.state_changes`.

- [ ] **Step 1: Write the failing tests**

`server/status/tests/test_models.py`:
```python
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from status.models import PC, CafeSettings
from status.state import IN_USE, Last


class CafeSettingsTests(TestCase):
    def test_load_creates_one_row_with_spec_defaults(self):
        first, second = CafeSettings.load(), CafeSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CafeSettings.objects.count(), 1)
        self.assertEqual(
            (first.idle_threshold_s, first.offline_timeout_s, first.heartbeat_interval_s,
             first.agents_enabled, first.allow_new_pcs),
            (600, 180, 60, True, False),
        )

    def test_timeout_must_cover_two_heartbeats(self):
        with self.assertRaises(ValidationError):
            CafeSettings(heartbeat_interval_s=120, offline_timeout_s=180).full_clean()
        CafeSettings(heartbeat_interval_s=60, offline_timeout_s=180).full_clean()  # fine


class PCTests(TestCase):
    def test_last_mirrors_live_fields(self):
        seen = timezone.now()
        pc = PC.objects.create(
            hostname="PC07", last_seen_at=seen, last_event="boot",
            idle_s_at_last_seen=5, state=IN_USE, state_since=seen,
        )
        self.assertEqual(pc.last(), Last(seen, "boot", 5, IN_USE, seen))

    def test_new_pc_is_off_and_shown_by_label(self):
        pc = PC.objects.create(hostname="PC07", label="Seat 7")
        self.assertEqual(pc.state, "off")
        self.assertEqual(str(pc), "Seat 7")
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `docker compose run --rm web python manage.py test status.tests.test_models`
Expected: `ImportError: cannot import name 'PC' from 'status.models'` (or `No module named 'status.models'`).

- [ ] **Step 3: Implement the models**

`server/status/models.py`:
```python
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .state import IDLE, IN_USE, OFF, Last


class CafeSettings(models.Model):
    """The single row of tunables, editable in admin (first_milestone.md §6.1)."""

    idle_threshold_s = models.PositiveIntegerField(default=600, validators=[MinValueValidator(60)])
    offline_timeout_s = models.PositiveIntegerField(default=180, validators=[MinValueValidator(60)])
    heartbeat_interval_s = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(30), MaxValueValidator(3600)]
    )
    agents_enabled = models.BooleanField(
        default=True, help_text="Untick to make every agent exit at its next heartbeat (remote off switch)."
    )
    allow_new_pcs = models.BooleanField(
        default=False,
        help_text="Tick while setting up so new PCs can register themselves with their first heartbeat; untick afterwards.",
    )

    class Meta:
        verbose_name = verbose_name_plural = "café settings"

    def __str__(self):
        return "Café settings"

    def clean(self):
        timeout, interval = self.offline_timeout_s, self.heartbeat_interval_s
        if None not in (timeout, interval) and timeout < 2 * interval:
            raise ValidationError(
                {"offline_timeout_s": "Must be at least twice the heartbeat interval, or PCs will flicker to Off."}
            )

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings


class PC(models.Model):
    STATES = [(IN_USE, "In use"), (IDLE, "Idle"), (OFF, "Off")]

    hostname = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64, blank=True)
    mac = models.CharField(max_length=17, blank=True)
    is_active = models.BooleanField(default=True, help_text="Untick to hide from the dashboard.")
    # Live fields, as of the last heartbeat.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_event = models.CharField(max_length=16, blank=True)
    idle_s_at_last_seen = models.PositiveIntegerField(default=0)
    boot_id = models.CharField(max_length=64, blank=True)
    agent_version = models.CharField(max_length=32, blank=True)
    state = models.CharField(max_length=8, choices=STATES, default=OFF)
    state_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "hostname"]
        verbose_name = "PC"

    def __str__(self):
        return self.label or self.hostname

    def last(self) -> Last:
        return Last(self.last_seen_at, self.last_event, self.idle_s_at_last_seen, self.state, self.state_since)


class StateChange(models.Model):
    """One row per state change. Future analytics (M4) are built on this; it can't be back-filled."""

    pc = models.ForeignKey(PC, on_delete=models.CASCADE, related_name="state_changes")
    from_state = models.CharField(max_length=8, choices=PC.STATES)
    to_state = models.CharField(max_length=8, choices=PC.STATES)
    at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["pc", "at"])]
        ordering = ["-at"]
```

- [ ] **Step 4: Implement the admin**

`server/status/admin.py`:
```python
from django.contrib import admin

from .models import PC, CafeSettings, StateChange


@admin.register(CafeSettings)
class CafeSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CafeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PC)
class PCAdmin(admin.ModelAdmin):
    list_display = ["hostname", "label", "state", "state_since", "last_seen_at", "agent_version", "is_active"]
    list_editable = ["label", "is_active"]
    readonly_fields = [
        "hostname", "mac", "last_seen_at", "last_event", "idle_s_at_last_seen",
        "boot_id", "agent_version", "state", "state_since", "created_at",
    ]

    def has_add_permission(self, request):
        return False  # PCs register themselves with their first heartbeat


@admin.register(StateChange)
class StateChangeAdmin(admin.ModelAdmin):
    list_display = ["at", "pc", "from_state", "to_state"]
    list_filter = ["pc", "to_state"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 5: Generate the migration**

Run: `docker compose run --rm web python manage.py makemigrations status`
Expected: `Migrations for 'status': status/migrations/0001_initial.py` listing `CafeSettings`, `PC`, `StateChange` and the index.

- [ ] **Step 6: Run all the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status`
Expected: `Ran 28 tests` … `OK`.

- [ ] **Step 7: Commit**

```bash
git add server/status/models.py server/status/admin.py server/status/migrations server/status/tests/test_models.py
git commit -m "feat: CafeSettings, PC and StateChange models with admin"
```

---

### Task 5: Heartbeat endpoint

**Files:**
- Modify: `server/status/views.py`, `server/status/urls.py`
- Test: `server/status/tests/test_heartbeat.py`

**Interfaces:**
- Consumes:
  - `settle` from `status.state`.
  - `PC`, `PC.last()`, `CafeSettings.load()` and `StateChange` from `status.models`.
  - `settings.AGENT_TOKEN_SHA256`.
- Produces: `POST /api/v1/heartbeat` (URL name `heartbeat`).
  - Returns 200 with `{"interval": int, "enabled": bool}`.
  - Returns 401 when the token is missing or wrong, 400 when the body is malformed, 403 for an unknown hostname while `allow_new_pcs` is off or once the 50-PC cap is reached, and 405 for anything other than POST.

- [ ] **Step 1: Write the failing tests**

`server/status/tests/test_heartbeat.py`:
```python
import hashlib
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from status.models import PC, CafeSettings

TOKEN = "test-token"
URL = "/api/v1/heartbeat"


def body(**fields):
    return json.dumps({"pc": "PC07", "event": "boot", "idle_s": 0, **fields}).encode()


@override_settings(AGENT_TOKEN_SHA256=hashlib.sha256(TOKEN.encode()).hexdigest())
class HeartbeatTests(TestCase):
    def setUp(self):
        CafeSettings.objects.create(pk=1, allow_new_pcs=True)

    def post(self, raw=None, auth=f"Bearer {TOKEN}", **fields):
        headers = {"Authorization": auth} if auth else {}
        return self.client.post(
            URL, data=raw if raw is not None else body(**fields), content_type="application/json", headers=headers
        )

    def test_missing_or_wrong_token_is_401(self):
        for auth in [None, "Bearer wrong", f"Basic {TOKEN}"]:
            with self.subTest(auth=auth):
                self.assertEqual(self.post(auth=auth).status_code, 401)
        self.assertFalse(PC.objects.exists())

    @override_settings(AGENT_TOKEN_SHA256="")
    def test_empty_configured_token_rejects_everything(self):
        self.assertEqual(self.post().status_code, 401)
        self.assertEqual(self.post(auth="Bearer ").status_code, 401)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_malformed_heartbeats_are_400(self):
        cases = {
            "not json": b"{nope",
            "json list": b"[]",
            "body over 1 KB": body(boot_id="x" * 2000),
            "space in hostname": body(pc="PC 07"),
            "hostname too long": body(pc="P" * 33),
            "hostname trailing newline": body(pc="PC07\n"),
            "unknown event": body(event="reboot"),
            "event not a string": body(event=["boot"]),
            "negative idle": body(idle_s=-1),
            "idle too large": body(idle_s=10**7 + 1),
            "idle as string": body(idle_s="5"),
            "idle as bool": body(idle_s=True),
            "idle as float": body(idle_s=5.0),
            "mac too long": body(mac="A" * 18),
            "mac not a string": body(mac=5),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post(raw=raw).status_code, 400)
        self.assertFalse(PC.objects.exists())

    def test_first_heartbeat_registers_pc_as_in_use(self):
        response = self.post(mac="AA:BB:CC:DD:EE:FF", boot_id="b1", agent_version="0.1.0")
        self.assertEqual(response.status_code, 200)
        pc = PC.objects.get()
        self.assertEqual((pc.hostname, pc.label, pc.state, pc.mac, pc.boot_id, pc.agent_version),
                         ("PC07", "PC07", "in_use", "AA:BB:CC:DD:EE:FF", "b1", "0.1.0"))
        self.assertIsNotNone(pc.last_seen_at)
        self.assertEqual(list(pc.state_changes.values_list("from_state", "to_state")), [("off", "in_use")])

    def test_hostname_is_case_insensitive(self):
        self.post(pc="pc07")
        self.post(pc="PC07", event="heartbeat")
        self.assertEqual(list(PC.objects.values_list("hostname", flat=True)), ["PC07"])

    def test_reply_carries_interval_and_enabled(self):
        CafeSettings.objects.update_or_create(pk=1, defaults={"heartbeat_interval_s": 120, "agents_enabled": False})
        self.assertEqual(self.post().json(), {"interval": 120, "enabled": False})

    def test_default_reply(self):
        self.assertEqual(self.post().json(), {"interval": 60, "enabled": True})

    def test_shutdown_is_off_immediately(self):
        self.post()
        self.post(event="shutdown")
        pc = PC.objects.get()
        self.assertEqual(pc.state, "off")
        self.assertEqual(
            list(pc.state_changes.order_by("at").values_list("from_state", "to_state")),
            [("off", "in_use"), ("in_use", "off")],
        )

    def test_unknown_pc_refused_while_new_pcs_not_allowed(self):
        PC.objects.create(hostname="PC01", label="PC01")
        CafeSettings.objects.filter(pk=1).update(allow_new_pcs=False)
        self.assertEqual(self.post(pc="PC07").status_code, 403)
        self.assertFalse(PC.objects.filter(hostname="PC07").exists())
        self.assertEqual(self.post(pc="PC01").status_code, 200)  # known PCs still report

    def test_pc_cap(self):
        PC.objects.bulk_create(PC(hostname=f"X{i}") for i in range(50))
        self.assertEqual(self.post(pc="PC07").status_code, 403)
        self.assertEqual(self.post(pc="X0").status_code, 200)  # known PCs still report

    def test_history_gets_exact_times(self):
        seen = timezone.now() - timedelta(seconds=60)
        pc = PC.objects.create(hostname="PC07", label="PC07", last_seen_at=seen, last_event="heartbeat",
                               idle_s_at_last_seen=590, state="in_use", state_since=seen)
        now = seen + timedelta(seconds=60)
        with mock.patch("status.views.timezone.now", return_value=now):
            self.post(event="heartbeat", idle_s=30)
        self.assertEqual(
            list(pc.state_changes.order_by("at").values_list("from_state", "to_state", "at")),
            [("in_use", "idle", seen + timedelta(seconds=10)), ("idle", "in_use", now - timedelta(seconds=30))],
        )
        pc.refresh_from_db()
        self.assertEqual((pc.state, pc.state_since, pc.last_seen_at, pc.idle_s_at_last_seen),
                         ("in_use", now - timedelta(seconds=30), now, 30))
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `docker compose run --rm web python manage.py test status.tests.test_heartbeat`
Expected: the tests fail with `404 != 401`, `404 != 400` and similar, because the route doesn't exist yet.

- [ ] **Step 3: Implement**

`server/status/views.py` (whole file):
```python
import hashlib
import hmac
import json
import re

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PC, CafeSettings, StateChange
from .state import settle

MAX_BODY_BYTES = 1024
MAX_PCS = 50
HOSTNAME = re.compile(r"[A-Za-z0-9-]{1,32}")
EVENTS = {"boot", "heartbeat", "shutdown"}
OPTIONAL_FIELDS = {"mac": 17, "boot_id": 64, "agent_version": 32}  # name -> max length


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def _authorized(request):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    digest = hashlib.sha256(token.encode()).hexdigest()
    return scheme == "Bearer" and hmac.compare_digest(digest, settings.AGENT_TOKEN_SHA256)


def _parse(raw):
    """The validated heartbeat as a dict, or None if anything is wrong (first_milestone.md §6.3)."""
    if len(raw) > MAX_BODY_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    pc, event, idle_s = data.get("pc"), data.get("event"), data.get("idle_s")
    if not (isinstance(pc, str) and HOSTNAME.fullmatch(pc)):
        return None
    if not (isinstance(event, str) and event in EVENTS):
        return None
    if type(idle_s) is not int or not 0 <= idle_s <= 10**7:  # `type is int` rejects True/False
        return None
    heartbeat = {"pc": pc.upper(), "event": event, "idle_s": idle_s}
    for name, max_len in OPTIONAL_FIELDS.items():
        value = data.get(name, "")
        if not isinstance(value, str) or len(value) > max_len:
            return None
        heartbeat[name] = value
    return heartbeat


@csrf_exempt
@require_POST
def heartbeat(request):
    if not _authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    hb = _parse(request.body)
    if hb is None:
        return JsonResponse({"error": "bad heartbeat"}, status=400)

    now = timezone.now()
    with transaction.atomic():
        cafe = CafeSettings.load()
        pc = PC.objects.select_for_update().filter(hostname=hb["pc"]).first()
        if pc is None:
            if not cafe.allow_new_pcs:
                return JsonResponse({"error": "unknown pc"}, status=403)
            if PC.objects.count() >= MAX_PCS:
                return JsonResponse({"error": "pc limit reached"}, status=403)
            pc = PC.objects.create(hostname=hb["pc"], label=hb["pc"])
        changes = settle(pc.last(), hb["event"], hb["idle_s"], now, cafe.idle_threshold_s, cafe.offline_timeout_s)
        for state, at in changes:
            StateChange.objects.create(pc=pc, from_state=pc.state, to_state=state, at=at)
            pc.state, pc.state_since = state, at
        pc.last_seen_at, pc.last_event, pc.idle_s_at_last_seen = now, hb["event"], hb["idle_s"]
        pc.mac, pc.boot_id, pc.agent_version = hb["mac"], hb["boot_id"], hb["agent_version"]
        pc.save()
    return JsonResponse({"interval": cafe.heartbeat_interval_s, "enabled": cafe.agents_enabled})
```

`server/status/urls.py` (whole file):
```python
from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("api/v1/heartbeat", views.heartbeat, name="heartbeat"),
]
```

- [ ] **Step 4: Run all the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status`
Expected: `Ran 40 tests` … `OK`.

- [ ] **Step 5: Commit**

```bash
git add server/status/views.py server/status/urls.py server/status/tests/test_heartbeat.py
git commit -m "feat: authenticated heartbeat endpoint with exact-time history"
```

---

### Task 6: Dashboard and login

**Files:**
- Modify: `server/status/views.py` (add `dashboard`, `_outage_minutes`), `server/status/urls.py`
- Create: `server/status/templates/status/dashboard.html`, `server/status/templates/registration/login.html`
- Test: `server/status/tests/test_dashboard.py`

**Interfaces:**
- Consumes:
  - `compute_state`, `IN_USE`, `IDLE` and `OFF` from `status.state`.
  - `PC`, `PC.STATES`, `PC.last()` and `CafeSettings.load()`.
- Produces: `GET /` (URL name `dashboard`), which requires login.
  - It renders the summary line `In use N · Idle N · Off N`, one tile per active PC (`<section class="tile {state}">`), and the outage banner when relevant.

- [ ] **Step 1: Write the failing tests**

`server/status/tests/test_dashboard.py`:
```python
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from status.models import PC


def make_pc(hostname, seen_ago=0, idle_s=0, event="heartbeat", active=True, seen=True):
    now = timezone.now()
    return PC.objects.create(
        hostname=hostname, label=hostname, is_active=active,
        last_seen_at=now - timedelta(seconds=seen_ago) if seen else None,
        last_event=event if seen else "", idle_s_at_last_seen=idle_s,
        state="in_use" if seen else "off", state_since=now if seen else None,
    )


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("staff", password="pw-123456789")

    def test_login_required(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/accounts/login/?next=/", fetch_redirect_response=False)

    def test_tiles_and_counts(self):
        make_pc("PC01")
        make_pc("PC02", idle_s=700)
        make_pc("PC03", seen=False)
        make_pc("PC04", active=False)
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertContains(response, "In use 1 · Idle 1 · Off 1")
        self.assertContains(response, '<section class="tile in_use">')
        self.assertContains(response, '<section class="tile idle">')
        self.assertContains(response, "PC03")
        self.assertNotContains(response, "PC04")
        self.assertContains(response, '<meta http-equiv="refresh" content="10">')  # inside <noscript>
        for element_id in ['id="summary"', 'id="banner-slot"', 'id="grid"']:  # swapped by the refresh script
            self.assertContains(response, element_id)
        self.assertNotContains(response, "No data from café")

    def test_outage_banner_when_cafe_goes_silent(self):
        make_pc("PC01", seen_ago=600)
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/"), "No data from café for 10 min")

    def test_no_banner_after_normal_closing(self):
        make_pc("PC01", seen_ago=3600)
        make_pc("PC02", seen_ago=600, event="shutdown")  # last PC to report shut down cleanly
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get("/"), "No data from café")

    @override_settings(ALLOWED_HOSTS=["abc.trycloudflare.com"], CSRF_TRUSTED_ORIGINS=["https://*.trycloudflare.com"])
    def test_login_through_quick_tunnel_passes_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/accounts/login/", HTTP_HOST="abc.trycloudflare.com")
        response = client.post(
            "/accounts/login/",
            {"username": "staff", "password": "pw-123456789", "csrfmiddlewaretoken": client.cookies["csrftoken"].value},
            HTTP_HOST="abc.trycloudflare.com",
            HTTP_ORIGIN="https://abc.trycloudflare.com",
        )
        self.assertEqual(response.status_code, 302)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `docker compose run --rm web python manage.py test status.tests.test_dashboard`
Expected: the tests fail. For example, `test_login_required` fails with a 404, and the login test errors with `TemplateDoesNotExist: registration/login.html`.

- [ ] **Step 3: Implement the view**

In `server/status/views.py`:
- Add these imports next to the existing ones:
  ```python
  from django.contrib.auth.decorators import login_required
  from django.shortcuts import render
  ```
- Change the line `from .state import settle` to:
  ```python
  from .state import IDLE, IN_USE, OFF, compute_state, settle
  ```
- Then append:
```python


STATE_LABELS = dict(PC.STATES)


def _outage_minutes(pcs, now, offline_timeout_s):
    """Minutes since the café last reported, if it looks like the internet is down (§6.2).

    If the most recent report was a clean shutdown, the café simply closed: no banner.
    """
    seen = [pc for pc in pcs if pc.last_seen_at]
    if not seen:
        return None
    latest = max(seen, key=lambda pc: pc.last_seen_at)
    silent_s = (now - latest.last_seen_at).total_seconds()
    if silent_s <= offline_timeout_s or latest.last_event == "shutdown":
        return None
    return int(silent_s // 60)


@login_required
def dashboard(request):
    now = timezone.now()
    cafe = CafeSettings.load()
    pcs = list(PC.objects.filter(is_active=True))
    tiles, counts = [], {IN_USE: 0, IDLE: 0, OFF: 0}
    for pc in pcs:
        state, since = compute_state(pc.last(), now, cafe.idle_threshold_s, cafe.offline_timeout_s)
        counts[state] += 1
        tiles.append({"pc": pc, "state": state, "label": STATE_LABELS[state], "since": since})
    return render(request, "status/dashboard.html", {
        "tiles": tiles,
        "counts": counts,
        "outage_minutes": _outage_minutes(pcs, now, cafe.offline_timeout_s),
        "now": now,
    })
```

`server/status/urls.py` (whole file):
```python
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("healthz", views.healthz, name="healthz"),
    path("api/v1/heartbeat", views.heartbeat, name="heartbeat"),
]
```

- [ ] **Step 4: Implement the templates**

`server/status/templates/status/dashboard.html`:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<noscript><meta http-equiv="refresh" content="10"></noscript>
<title>Café PCs</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem; background: #f6f6f6; color: #111; }
  header { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: .5rem; }
  h1 { margin: 0; }
  .banner { background: #fff3cd; border: 1px solid #c9a227; padding: .75rem; margin: 1rem 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr)); gap: .5rem; margin-top: 1rem; }
  .tile { background: #fff; border-radius: .5rem; padding: .75rem; border-left: .5rem solid; }
  .tile h2 { margin: 0 0 .25rem; font-size: 1.1rem; }
  .tile p { margin: 0; }
  .state { font-weight: 700; }
  .in_use { border-color: #1a7f37; }
  .idle { border-color: #c9a227; }
  .off { border-color: #8c8c8c; color: #555; }
</style>
</head>
<body>
<header>
  <h1>Café PCs</h1>
  <p id="summary">In use {{ counts.in_use }} · Idle {{ counts.idle }} · Off {{ counts.off }}</p>
  <form method="post" action="{% url 'logout' %}">{% csrf_token %}<button type="submit">Log out</button></form>
</header>
<div id="banner-slot">
{% if outage_minutes is not None %}
<p class="banner" role="alert">No data from café for {{ outage_minutes }} min — internet may be down; statuses may be stale.</p>
{% endif %}
</div>
<main class="grid" id="grid">
{% for t in tiles %}
  <section class="tile {{ t.state }}">
    <h2>{{ t.pc }}</h2>
    <p class="state">{{ t.label }}</p>
    {% if t.since %}<p>{% if t.state == "off" %}since {{ t.since|time:"H:i" }}{% else %}for {{ t.since|timesince:now }}{% endif %}</p>{% endif %}
  </section>
{% empty %}
  <p>No PCs have reported yet.</p>
{% endfor %}
</main>
<script>
// Swap in fresh tiles every 10 s without reloading the page (no flash, no scroll jump).
setInterval(async () => {
  try {
    const response = await fetch(location.href, { cache: "no-store" });
    if (!response.ok || response.redirected) { location.reload(); return; }  // e.g. logged out
    const fresh = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const id of ["summary", "banner-slot", "grid"]) {
      document.getElementById(id).replaceWith(fresh.getElementById(id));
    }
  } catch (error) { /* network blip: keep showing the last view */ }
}, 10000);
</script>
</body>
</html>
```

`server/status/templates/registration/login.html`:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Log in — Café PCs</title>
</head>
<body style="font-family: system-ui, sans-serif; max-width: 22rem; margin: 3rem auto; padding: 0 1rem;">
<h1>Café PCs</h1>
{% if form.errors %}<p role="alert">Wrong username or password.</p>{% endif %}
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <input type="hidden" name="next" value="{{ next }}">
  <button type="submit">Log in</button>
</form>
</body>
</html>
```

- [ ] **Step 5: Run all the tests and confirm they pass**

Run: `docker compose run --rm web python manage.py test status`
Expected: `Ran 45 tests` … `OK`.

- [ ] **Step 6: Look at it in a browser**

From PowerShell in `deploy/`, run `docker compose exec web python manage.py createsuperuser` and choose a username and password.
Then open `http://localhost:8000/` and log in. Expected: the dashboard says "No PCs have reported yet."
Open `http://localhost:8000/admin/`. Expected: "Café settings", "PCs" and "State changes" are listed, and the admin is styled (its CSS loads).

- [ ] **Step 7: Commit**

```bash
git add server/status/views.py server/status/urls.py server/status/templates server/status/tests/test_dashboard.py
git commit -m "feat: staff dashboard with live tiles, counts and outage banner"
```

---

### Task 7: Go agent

**Files:**
- Create: `agent/go.mod` (generated), `agent/main.go`, `agent/main_test.go`
- Modify: `.gitignore` (add `*.exe`)

**Interfaces:**
- Consumes: `POST /api/v1/heartbeat` from Task 5, and its reply `{"interval", "enabled"}`.
- Produces: `cafe-agent.exe`, run as `cafe-agent.exe [-url URL] [-token TOKEN]`. The compiled-in defaults can be set with `-ldflags "-X main.serverURL=… -X main.token=… -X main.version=…"`.

- [ ] **Step 1: Initialise the module**

Open a **new** terminal so Go is on the PATH, then run:
```bash
cd agent
go mod init cafe-agent
```
Expected: `go: creating new go.mod: module cafe-agent`.

- [ ] **Step 2: Write the failing tests**

`agent/main_test.go`:
```go
package main

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestIdleSeconds(t *testing.T) {
	cases := []struct {
		name             string
		tick, last, want uint32
	}{
		{"just touched", 5000, 5000, 0},
		{"rounds down", 5999, 2000, 3},
		{"tick counter wrapped after 49.7 days", 1000, math.MaxUint32 - 999, 2},
	}
	for _, c := range cases {
		if got := idleSeconds(c.tick, c.last); got != c.want {
			t.Errorf("%s: idleSeconds(%d, %d) = %d, want %d", c.name, c.tick, c.last, got, c.want)
		}
	}
}

func TestClampInterval(t *testing.T) {
	cases := map[int]time.Duration{
		-5: 30 * time.Second, 0: 30 * time.Second, 29: 30 * time.Second,
		60: time.Minute, 3600: time.Hour, 99999: time.Hour,
	}
	for in, want := range cases {
		if got := clampInterval(in); got != want {
			t.Errorf("clampInterval(%d) = %v, want %v", in, got, want)
		}
	}
}

func TestPadActive(t *testing.T) {
	cases := []struct {
		name string
		s    padState
		want bool
	}{
		{"resting", padState{}, false},
		{"stick drift inside deadzone", padState{LX: 7000, LY: -7000, RX: 8000, RY: -8000}, false},
		{"light trigger noise", padState{LeftTrigger: 30}, false},
		{"button held", padState{Buttons: 0x1000}, true},
		{"left stick pushed", padState{LX: 7850}, true},
		{"right stick pushed fully left", padState{RX: math.MinInt16}, true},
		{"trigger pressed", padState{RightTrigger: 31}, true},
	}
	for _, c := range cases {
		if got := c.s.active(); got != c.want {
			t.Errorf("%s: active() = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestGamepadsTrackInput(t *testing.T) {
	t0 := time.Date(2026, 10, 1, 12, 0, 0, 0, time.UTC)
	var g gamepads
	if _, ok := g.idleSince(t0); ok {
		t.Fatal("no controller input yet")
	}
	g.observe(0, t0, padState{}, true) // plugged in, resting
	if _, ok := g.idleSince(t0); ok {
		t.Fatal("a resting controller is not input")
	}
	g.observe(0, t0.Add(5*time.Second), padState{Buttons: 1}, true) // pressed
	g.observe(0, t0.Add(10*time.Second), padState{}, true)          // released: a change counts too
	if s, ok := g.idleSince(t0.Add(70 * time.Second)); !ok || s != 60 {
		t.Errorf("idleSince = %d, %v; want 60, true", s, ok)
	}
}

func TestEmptySlotsProbedOncePerMinute(t *testing.T) {
	t0 := time.Date(2026, 10, 1, 12, 0, 0, 0, time.UTC)
	var g gamepads
	if !g.due(1, t0) {
		t.Fatal("a never-probed slot must be due")
	}
	g.observe(1, t0, padState{}, false) // nothing plugged in
	if g.due(1, t0.Add(59*time.Second)) {
		t.Error("empty slot re-probed too soon")
	}
	if !g.due(1, t0.Add(time.Minute)) {
		t.Error("empty slot not re-probed after a minute")
	}
	g.observe(1, t0.Add(time.Minute), padState{}, true) // plugged in
	if !g.due(1, t0.Add(time.Minute+5*time.Second)) {
		t.Error("a connected slot must be polled every time")
	}
}

func TestIdleNowUsesControllerInput(t *testing.T) {
	g := &gamepads{}
	g.observe(0, time.Now().Add(-3*time.Second), padState{Buttons: 1}, true)
	if idle := (&agent{pads: g}).idleNow(); idle > 3 {
		t.Errorf("idleNow() = %d, want <= 3 right after controller input", idle)
	}
}

func TestSendPostsHeartbeatAndReadsReply(t *testing.T) {
	var got payload
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		json.NewDecoder(r.Body).Decode(&got)
		w.Write([]byte(`{"interval": 120, "enabled": false}`))
	}))
	defer srv.Close()

	a := &agent{url: srv.URL, token: "secret", client: srv.Client(),
		base: payload{PC: "PC07", BootID: "b1", AgentVersion: "test"}}
	r, err := a.send(context.Background(), "boot")
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer secret" || got.PC != "PC07" || got.Event != "boot" || got.BootID != "b1" {
		t.Errorf("server received auth=%q payload=%+v", auth, got)
	}
	if r.Interval != 120 || r.Enabled {
		t.Errorf("reply = %+v, want interval 120, enabled false", r)
	}
}

func TestSendDefaultsMissingReplyFields(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
	defer srv.Close()
	r, err := (&agent{url: srv.URL, client: srv.Client()}).send(context.Background(), "heartbeat")
	if err != nil || r.Interval != 60 || !r.Enabled {
		t.Errorf("reply = %+v, err = %v; want interval 60, enabled true", r, err)
	}
}

func TestSendTreatsNon200AsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "no", http.StatusUnauthorized)
	}))
	defer srv.Close()
	if _, err := (&agent{url: srv.URL, client: srv.Client()}).send(context.Background(), "heartbeat"); err == nil {
		t.Fatal("want an error for a 401 reply")
	}
}
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `go test ./...`
Expected: a build failure: `undefined: idleSeconds`, `undefined: padState`, `undefined: agent` and similar.

- [ ] **Step 4: Implement**

`agent/main.go`:
```go
// Command cafe-agent reports "seconds since last keyboard, mouse or controller input"
// to the café status server: a boot event, a heartbeat every interval, and a shutdown
// event (first_milestone.md §5). Report-only: no hooks, no disk writes, and it runs in
// Windows background mode so games keep the CPU, disk and memory.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	mrand "math/rand/v2"
	"net"
	"net/http"
	"os"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

// Defaults, overridable at build time:
//
//	go build -ldflags "-X main.serverURL=https://... -X main.token=... -X main.version=1.0.0"
var (
	serverURL = "http://localhost:8000/api/v1/heartbeat"
	token     = ""
	version   = "dev"
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	xinput   = syscall.NewLazyDLL("xinput1_4.dll")

	procGetLastInputInfo  = user32.NewProc("GetLastInputInfo")
	procRegisterClassExW  = user32.NewProc("RegisterClassExW")
	procCreateWindowExW   = user32.NewProc("CreateWindowExW")
	procDefWindowProcW    = user32.NewProc("DefWindowProcW")
	procGetMessageW       = user32.NewProc("GetMessageW")
	procDispatchMessageW  = user32.NewProc("DispatchMessageW")
	procGetTickCount      = kernel32.NewProc("GetTickCount")
	procGetTickCount64    = kernel32.NewProc("GetTickCount64")
	procGetCurrentProcess = kernel32.NewProc("GetCurrentProcess")
	procSetPriorityClass  = kernel32.NewProc("SetPriorityClass")
	procGetModuleHandleW  = kernel32.NewProc("GetModuleHandleW")
	procXInputGetState    = xinput.NewProc("XInputGetState")
)

const (
	processModeBackgroundBegin = 0x00100000 // low CPU, I/O and memory priority
	wmQueryEndSession          = 0x0011
	wmEndSession               = 0x0016

	// Deadzones recommended by Microsoft (XInput.h); stick drift stays inside them.
	leftStickDeadzone  = 7849
	rightStickDeadzone = 8689
	triggerThreshold   = 30
)

type payload struct {
	PC           string `json:"pc"`
	MAC          string `json:"mac"`
	Event        string `json:"event"`
	IdleS        uint32 `json:"idle_s"`
	BootID       string `json:"boot_id"`
	UptimeS      uint64 `json:"uptime_s"`
	AgentVersion string `json:"agent_version"`
}

type reply struct {
	Interval int  `json:"interval"`
	Enabled  bool `json:"enabled"`
}

type agent struct {
	url, token string
	client     *http.Client
	pads       *gamepads // nil when XInput isn't available
	base       payload   // the fields that never change while running
}

// idleSeconds is correct across the 49.7-day wrap of the 32-bit tick counter.
func idleSeconds(tickMs, lastInputMs uint32) uint32 { return (tickMs - lastInputMs) / 1000 }

// clampInterval keeps a server-sent interval within 30 s – 1 h.
func clampInterval(seconds int) time.Duration {
	return time.Duration(min(max(seconds, 30), 3600)) * time.Second
}

// padState is XINPUT_GAMEPAD: the part of a controller's state that shows a person is playing.
type padState struct {
	Buttons                   uint16
	LeftTrigger, RightTrigger uint8
	LX, LY, RX, RY            int16
}

func outside(x, y int16, deadzone int32) bool {
	ax, ay := int32(x), int32(y)
	return ax > deadzone || ax < -deadzone || ay > deadzone || ay < -deadzone
}

// active: a button held, a trigger pressed, or a stick pushed past its deadzone.
func (s padState) active() bool {
	return s.Buttons != 0 || s.LeftTrigger > triggerThreshold || s.RightTrigger > triggerThreshold ||
		outside(s.LX, s.LY, leftStickDeadzone) || outside(s.RX, s.RY, rightStickDeadzone)
}

// gamepads remembers when a controller was last used. Windows' input counter ignores
// XInput controllers, so without this a controller-only player would look Idle.
// Polled from one goroutine and read from another, hence the mutex.
type gamepads struct {
	mu        sync.Mutex
	prev      [4]padState
	connected [4]bool
	nextProbe [4]time.Time
	lastInput time.Time
}

// due reports whether slot i should be polled now: connected slots every time,
// empty slots once a minute (probing an unplugged slot is slow).
func (g *gamepads) due(i int, now time.Time) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.connected[i] || !now.Before(g.nextProbe[i])
}

// observe records one poll of slot i; ok is false when nothing is plugged in.
func (g *gamepads) observe(i int, now time.Time, s padState, ok bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if !ok {
		g.connected[i], g.nextProbe[i] = false, now.Add(time.Minute)
		return
	}
	if s.active() || (g.connected[i] && s.Buttons != g.prev[i].Buttons) {
		g.lastInput = now
	}
	g.connected[i], g.prev[i] = true, s
}

// idleSince is whole seconds since the last controller input, if there was any.
func (g *gamepads) idleSince(now time.Time) (uint32, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.lastInput.IsZero() {
		return 0, false
	}
	return uint32(now.Sub(g.lastInput) / time.Second), true
}

// readPad polls controller slot i (0-3) through XInputGetState.
func readPad(i int) (padState, bool) {
	var st struct { // XINPUT_STATE
		packet uint32
		pad    padState
	}
	r, _, _ := procXInputGetState.Call(uintptr(i), uintptr(unsafe.Pointer(&st)))
	return st.pad, r == 0 // 0 = ERROR_SUCCESS; anything else = not connected
}

// pollGamepads checks controllers 0-3 every 5 s, forever.
// ponytail: sampling, so a tap released between two samples is missed; real play
// holds sticks and triggers. Poll faster only if Phase 2 shows false Idles.
func pollGamepads(g *gamepads) {
	for {
		now := time.Now()
		for i := 0; i < 4; i++ {
			if g.due(i, now) {
				s, ok := readPad(i)
				g.observe(i, now, s, ok)
			}
		}
		time.Sleep(5 * time.Second)
	}
}

func currentIdleSeconds() uint32 {
	info := struct{ cbSize, dwTime uint32 }{cbSize: 8} // LASTINPUTINFO
	procGetLastInputInfo.Call(uintptr(unsafe.Pointer(&info)))
	tick, _, _ := procGetTickCount.Call()
	return idleSeconds(uint32(tick), info.dwTime)
}

// idleNow is the time since the latest keyboard, mouse or controller input.
func (a *agent) idleNow() uint32 {
	idle := currentIdleSeconds()
	if a.pads != nil {
		if s, ok := a.pads.idleSince(time.Now()); ok && s < idle {
			idle = s
		}
	}
	return idle
}

func uptimeSeconds() uint64 {
	ms, _, _ := procGetTickCount64.Call()
	return uint64(ms) / 1000
}

func enterBackgroundMode() {
	self, _, _ := procGetCurrentProcess.Call()
	procSetPriorityClass.Call(self, processModeBackgroundBegin)
}

func newBootID() string {
	b := make([]byte, 8)
	rand.Read(b)
	return hex.EncodeToString(b)
}

// primaryMAC is the MAC of the first up, non-loopback interface with an IPv4 address.
func primaryMAC() string {
	ifaces, _ := net.Interfaces()
	for _, i := range ifaces {
		if i.Flags&net.FlagUp == 0 || i.Flags&net.FlagLoopback != 0 || len(i.HardwareAddr) != 6 {
			continue
		}
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			if ip, ok := a.(*net.IPNet); ok && ip.IP.To4() != nil {
				return strings.ToUpper(i.HardwareAddr.String())
			}
		}
	}
	return ""
}

// send posts one event and returns the server's reply. ctx bounds how long it may take.
func (a *agent) send(ctx context.Context, event string) (reply, error) {
	p := a.base
	p.Event = event
	p.IdleS = a.idleNow()
	p.UptimeS = uptimeSeconds()
	body, err := json.Marshal(p)
	if err != nil {
		return reply{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.url, bytes.NewReader(body))
	if err != nil {
		return reply{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+a.token)
	resp, err := a.client.Do(req)
	if err != nil {
		return reply{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return reply{}, fmt.Errorf("server replied %s", resp.Status)
	}
	r := reply{Interval: 60, Enabled: true} // kept if the server omits a field
	err = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&r)
	return r, err
}

type wndClassEx struct { // WNDCLASSEXW
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     uintptr
	hIcon         uintptr
	hCursor       uintptr
	hbrBackground uintptr
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       uintptr
}

type winMsg struct { // MSG
	hwnd     uintptr
	message  uint32
	wParam   uintptr
	lParam   uintptr
	time     uint32
	pt       struct{ x, y int32 }
	lPrivate uint32
}

// watchSessionEnd runs a hidden top-level window and calls onEnd when Windows shuts
// down or logs off. It must be top-level: message-only windows don't get WM_ENDSESSION.
// (SetConsoleCtrlHandler is no alternative: programs with a window never receive
// console shutdown signals.)
func watchSessionEnd(onEnd func()) {
	runtime.LockOSThread() // a window's messages arrive on the thread that created it
	className, _ := syscall.UTF16PtrFromString("CafeAgentWindow")
	instance, _, _ := procGetModuleHandleW.Call(0)
	wndProc := syscall.NewCallback(func(hwnd, msg, wParam, lParam uintptr) uintptr {
		switch msg {
		case wmQueryEndSession:
			return 1 // never block a shutdown
		case wmEndSession:
			if wParam != 0 {
				onEnd()
			}
			return 0
		}
		r, _, _ := procDefWindowProcW.Call(hwnd, msg, wParam, lParam)
		return r
	})
	wc := wndClassEx{lpfnWndProc: wndProc, hInstance: instance, lpszClassName: className}
	wc.cbSize = uint32(unsafe.Sizeof(wc))
	procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
	procCreateWindowExW.Call(0, uintptr(unsafe.Pointer(className)), 0, 0, 0, 0, 0, 0, 0, 0, instance, 0)
	var m winMsg
	for {
		r, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			return
		}
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func main() {
	url := flag.String("url", serverURL, "heartbeat endpoint")
	tok := flag.String("token", token, "agent token")
	flag.Parse()

	enterBackgroundMode()
	host, _ := os.Hostname()
	a := &agent{url: *url, token: *tok, client: &http.Client{}, base: payload{
		PC: host, MAC: primaryMAC(), BootID: newBootID(), AgentVersion: version,
	}}
	if procXInputGetState.Find() == nil { // xinput1_4.dll ships with Windows 8 and later
		a.pads = &gamepads{}
		go pollGamepads(a.pads)
	}

	// The shutdown message reuses a.client's open connection: no new TLS handshake
	// while Windows is shutting down. If it is lost, silence still marks the PC Off.
	go watchSessionEnd(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		a.send(ctx, "shutdown")
	})

	// Spread the first report so 30 PCs switched on together don't arrive in the same second.
	time.Sleep(time.Duration(mrand.IntN(31)) * time.Second)

	event := "boot"
	for {
		interval := time.Minute
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		r, err := a.send(ctx, event)
		cancel()
		if err == nil {
			if !r.Enabled {
				return // remote off switch: stay quiet until the next boot
			}
			interval = clampInterval(r.Interval)
		} // on error: drop it and try again next tick (no queue, nothing on disk)
		event = "heartbeat"
		time.Sleep(interval)
	}
}
```

- [ ] **Step 5: Run the tests and vet, and confirm both pass**

Run: `go vet ./... && go test ./...`
Expected: `ok  	cafe-agent`, with no `go vet` output.

- [ ] **Step 6: Build the exe**

Run: `go build -trimpath -ldflags "-H windowsgui -s -w -X main.version=0.1.0" -o cafe-agent.exe .`
Expected: `agent/cafe-agent.exe` exists. Check with `ls -la cafe-agent.exe`; it should be roughly 6–8 MB.

- [ ] **Step 7: Ignore built exes and commit**

```bash
cd ..
printf '*.exe\n' >> .gitignore
git add .gitignore agent/go.mod agent/main.go agent/main_test.go
git status --short   # cafe-agent.exe must NOT be listed
git commit -m "feat: Go status agent (idle time, boot/heartbeat/shutdown)"
```

---

### Task 8: PC simulator

**Files:**
- Create: `tools/simulate_pcs.py`

**Interfaces:**
- Consumes: `POST /api/v1/heartbeat` from Task 5.
- Produces: the CLI `python tools/simulate_pcs.py --token TOKEN [--url URL] [--first 2] [--count 29] [--interval 60] [--ticks 0] [--seed N]`. It prints one line per tick, with the number of PCs in each mode and the HTTP status codes received.

- [ ] **Step 1: Write the simulator**

`tools/simulate_pcs.py`:
```python
"""Pretend to be café PCs PC02..PC30, so the dashboard can be tested without the café.

Each tick every virtual PC is either playing (recent input), away (idle time grows)
or off (one shutdown message, then silence). About 5% of PCs change mode each tick.
Standard library only.

Example:
  python tools/simulate_pcs.py --token <AGENT TOKEN> --interval 15
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter

PLAYING, AWAY, OFF = "playing", "away", "off"


class VirtualPC:
    def __init__(self, name, mode, idle_s=0):
        self.name, self.mode, self.idle_s = name, mode, idle_s
        self.on = mode != OFF

    def step(self, rng, interval):
        """Advance one tick. Returns the event to send, or None to stay silent."""
        if rng.random() < 0.05:
            self.mode = rng.choice([PLAYING, AWAY, OFF])
        if self.mode == OFF:
            was_on, self.on = self.on, False
            return "shutdown" if was_on else None
        if not self.on:
            self.on, self.idle_s = True, 0
            return "boot"
        self.idle_s = rng.randint(0, 20) if self.mode == PLAYING else self.idle_s + interval
        return "heartbeat"


def send(url, token, pc, event):
    data = json.dumps({
        "pc": pc.name, "event": event, "idle_s": pc.idle_s,
        "boot_id": f"sim-{pc.name}", "agent_version": "simulator",
    }).encode()
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except urllib.error.URLError as error:
        return f"unreachable ({error.reason})"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000/api/v1/heartbeat")
    parser.add_argument("--token", required=True, help="the agent token (not its hash)")
    parser.add_argument("--first", type=int, default=2, help="number of the first virtual PC (2 = PC02)")
    parser.add_argument("--count", type=int, default=29, help="number of virtual PCs")
    parser.add_argument("--interval", type=int, default=60, help="seconds between ticks")
    parser.add_argument("--ticks", type=int, default=0, help="stop after N ticks (0 = run until Ctrl+C)")
    parser.add_argument("--seed", type=int, help="make the run repeatable")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    pcs = []
    for i in range(args.count):  # roughly 2/3 playing, 1/6 away, 1/6 off
        mode = OFF if i % 6 == 5 else AWAY if i % 6 == 4 else PLAYING
        pcs.append(VirtualPC(f"PC{args.first + i:02d}", mode, idle_s=rng.randint(300, 900) if mode == AWAY else 0))

    tick = 0
    while args.ticks == 0 or tick < args.ticks:
        tick += 1
        responses = Counter()
        for pc in pcs:
            event = pc.step(rng, args.interval)
            if event:
                responses[send(args.url, args.token, pc, event)] += 1
        modes = Counter(pc.mode for pc in pcs)
        print(f"tick {tick}: playing {modes[PLAYING]}, away {modes[AWAY]}, off {modes[OFF]}; "
              f"responses {dict(responses)}", flush=True)
        if args.ticks == 0 or tick < args.ticks:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Set the agent token on the server**

Run on the laptop:
```bash
python -c "import secrets, hashlib; t = secrets.token_urlsafe(32); print('TOKEN (give to agents):', t); print('AGENT_TOKEN_SHA256=' + hashlib.sha256(t.encode()).hexdigest())"
```
Paste the `AGENT_TOKEN_SHA256=…` line into `deploy/.env`. Keep the TOKEN somewhere safe, such as a password manager; don't put it in git. Then run, from `deploy/`: `docker compose up -d`. Expected: `web` is recreated (`Recreated`/`Started`).
Then go to admin → Café settings and tick **Allow new PCs**, so the simulated and real PCs can register themselves. Without it, every new hostname gets 403.

- [ ] **Step 3: Smoke-test against the stack**

Run: `python tools/simulate_pcs.py --token <TOKEN> --ticks 1 --seed 1`
Expected: `tick 1: …; responses {200: N}`, where N is 20–25 and **only** 200s appear.
Run it again with a wrong token: `python tools/simulate_pcs.py --token wrong --ticks 1 --seed 1`. Expected: `responses {401: N}`.
Refresh `http://localhost:8000/`. Expected: tiles PC02–PC30 are present, and the summary line counts them.

- [ ] **Step 4: Commit**

```bash
git add tools/simulate_pcs.py
git commit -m "feat: simulator for PC02..PC30"
```

---

### Task 9: End-to-end rehearsal on the laptop (human, ~30 min)

This checks the spec's acceptance timings (§9) with the real agent, so the owner demo holds no surprises. Record each result as pass or fail in the commit message at the end.

- [ ] **Step 1: Shorten the threshold for the rehearsal**

Go to admin → Café settings and set the idle threshold to `60` s. Keep the offline timeout at `180` and the heartbeat interval at `60`.

- [ ] **Step 2: Start the simulated PCs**

In a separate terminal: `python tools/simulate_pcs.py --token <TOKEN> --interval 15`

- [ ] **Step 3: Start the real agent as the laptop's own tile**

Run from `agent/`: `./cafe-agent.exe -token <TOKEN>`. The exe has no window and returns immediately.
Expected: within 30 s, a tile with the laptop's hostname (in capitals) shows **In use**.

- [ ] **Step 4: Check idle detection**

Keep your hands off the keyboard and mouse.
Expected: the tile shows **Idle** within about 70 s (60 s threshold plus one 10 s refresh).
Move the mouse. Expected: **In use** within about 70 s (next heartbeat plus one refresh).

- [ ] **Step 5: Check the resource budget**

Open Task Manager → Details → `cafe-agent.exe`.
Expected: Memory (active private working set) ≤ 15 MB, and CPU shows 00.
Optionally, Sysinternals Process Explorer → Properties → Performance shows the CPU time staying near 0.

- [ ] **Step 6: Simulate a power cut**

Run `taskkill //IM cafe-agent.exe //F` (double slashes in Git Bash). A forced kill sends no shutdown message, just like pulling the plug.
Expected: the tile shows **Off** within 3 min 10 s.

- [ ] **Step 7: Check the remote off switch**

Go to admin → Café settings and untick "Agents enabled". Start `./cafe-agent.exe -token <TOKEN>` again.
Expected: after its first heartbeat (≤ 30 s), `cafe-agent.exe` disappears from Task Manager.
Tick "Agents enabled" again afterwards. The simulator ignores this flag, so its tiles keep updating throughout.

- [ ] **Step 8: Check the outage banner**

Stop the simulator (Ctrl+C) and make sure no agent is running. Wait 4 minutes.
Expected: the yellow banner reads "No data from café for 3 min" or 4.

- [ ] **Step 9: Check the history**

Go to admin → State changes, and filter by the laptop's PC.
Expected: rows for in use → idle → in use → off, with times that match what you saw.

- [ ] **Step 10: Check the phone over the quick tunnel**

```bash
winget install --id Cloudflare.cloudflared -e
cloudflared tunnel --url http://localhost:8000
```
Open the printed `https://….trycloudflare.com` link on your phone and log in.
Expected: the dashboard loads and refreshes every 10 s. There's no CSRF error when logging in.

- [ ] **Step 11: Restore the settings and record the results**

Set the idle threshold back to `600`, or leave it at `120` for the owner demo so changes show up quickly. Then:
```bash
git commit --allow-empty -m "test: laptop end-to-end rehearsal passed

<list each step 3-10: pass/fail + measured RAM of cafe-agent.exe>"
```

---

### Task 10: Café benchmark and owner demo (human, at the café, outside busy hours)

This is spec Phase 2 and Phase 2b. Get the owner's permission first. Every agent run here is temporary: on a diskless PC, files copied to the Desktop live in CCBoot's write-back cache and **vanish on reboot**.

**Bring:**
- The laptop with the stack running.
- `cafe-agent.exe` and the TOKEN on a USB stick.
- PresentMon or CapFrameX, Process Explorer and Process Monitor (Sysinternals).

- [ ] **Step 1: Start the tunnel and simulator on the laptop**

Connect the laptop to the café Wi-Fi or LAN and run `cloudflared tunnel --url http://localhost:8000`. Note the URL; it changes on every run.
Start the simulator with `--count 27` and a `--first` that avoids the real PCs' names, so the 3 real PCs fill the remaining tiles. For example, if the real PCs are PC01–PC03, use `--first 4 --count 27`.

- [ ] **Step 2: Measure a baseline on one PC without the agent**

Use the 3 most-played games and do 3 runs of each. Record average FPS, 1% low FPS, CPU and RAM use, and in-game ping in `docs/benchmark-results.md`, using the template below.

- [ ] **Step 3: Start the agent on that PC**

Copy `cafe-agent.exe` to the Desktop and run, from a command prompt:
`cafe-agent.exe -url https://<quick-tunnel>.trycloudflare.com/api/v1/heartbeat -token <TOKEN>`
Expected: its tile appears on the dashboard. If Windows SmartScreen or Defender blocks the exe, note it in the results; it's the risk of an unsigned exe (spec §13).

- [ ] **Step 4: Measure again with the agent running**

Repeat Step 2 exactly. Pass condition: average FPS and 1% lows are within 2% of the baseline.

- [ ] **Step 5: Check for disk writes**

In Process Monitor, filter on `Process Name is cafe-agent.exe` and `Operation is WriteFile`.
Expected: no events after startup.

- [ ] **Step 6: Check every anti-cheat game**

Launch every anti-cheat game the café runs while the agent is running.
Expected: no kicks, no warnings and no Defender alerts.

- [ ] **Step 7: Run the owner demo**

Start the agent on 2 more PCs. Show the dashboard on the owner's phone while a gamer plays, someone walks away (Idle), and one PC shuts down (Off within 15 s). Show the benchmark numbers.

- [ ] **Step 8: Clean up**

Reboot the 3 PCs; the agent and its exe disappear. Stop the tunnel.

- [ ] **Step 9: Record the results and commit**

`docs/benchmark-results.md` template:
```markdown
# Benchmark results: <date>, PC <hostname>

| Game (anti-cheat) | Run | Avg FPS (no agent) | 1% low (no agent) | Avg FPS (agent) | 1% low (agent) |
|---|---|---|---|---|---|
| | 1 | | | | |
| | 2 | | | | |
| | 3 | | | | |

- cafe-agent.exe RAM (private working set): __ MB, CPU: __ %
- Disk writes after startup (Process Monitor): __
- Anti-cheat / SmartScreen / Defender incidents: __
- Owner feedback: __
- Verdict against first_milestone.md §9: pass / fail (why)
```
Then commit:
```bash
git add docs/benchmark-results.md
git commit -m "docs: café benchmark and owner demo results"
```
