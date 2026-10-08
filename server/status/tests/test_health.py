from django.test import SimpleTestCase


class HealthTests(SimpleTestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
