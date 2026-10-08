import hashlib
import hmac
import json
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PC, CafeSettings, StateChange
from .state import IDLE, IN_USE, OFF, compute_state, settle

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
