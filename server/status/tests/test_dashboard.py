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
