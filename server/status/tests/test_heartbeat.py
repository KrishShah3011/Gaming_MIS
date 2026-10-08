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
