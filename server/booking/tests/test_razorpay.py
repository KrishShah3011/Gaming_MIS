import base64
import hashlib
import hmac
import io
import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from booking import razorpay


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="secret", RAZORPAY_WEBHOOK_SECRET="hook")
class RazorpayTests(SimpleTestCase):
    @patch("booking.razorpay.urllib.request.urlopen")
    def test_create_order_posts_paise_with_basic_auth(self, urlopen):
        urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"id": "order_42"}')
        self.assertEqual(razorpay.create_order(50000, "r1"), "order_42")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.razorpay.com/v1/orders")
        self.assertEqual(json.loads(request.data), {"amount": 50000, "currency": "INR", "receipt": "r1"})
        self.assertEqual(request.get_header("Authorization"), "Basic " + base64.b64encode(b"rzp_test_x:secret").decode())

    def test_payment_signature(self):
        good = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
        self.assertTrue(razorpay.payment_signature_ok("order_1", "pay_1", good))
        self.assertFalse(razorpay.payment_signature_ok("order_1", "pay_2", good))

    def test_webhook_signature(self):
        body = b'{"event": "payment.captured"}'
        self.assertTrue(razorpay.webhook_signature_ok(body, hmac.new(b"hook", body, hashlib.sha256).hexdigest()))
        self.assertFalse(razorpay.webhook_signature_ok(body, "nope"))

    @override_settings(RAZORPAY_KEY_SECRET="", RAZORPAY_WEBHOOK_SECRET="")
    def test_empty_secrets_reject_everything(self):
        body = b"{}"
        self.assertFalse(razorpay.webhook_signature_ok(body, hmac.new(b"", body, hashlib.sha256).hexdigest()))
        self.assertFalse(razorpay.payment_signature_ok("o", "p", hmac.new(b"", b"o|p", hashlib.sha256).hexdigest()))
