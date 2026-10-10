"""Razorpay with the standard library only: one API call and two signature checks (m2 spec §6)."""
import base64
import hashlib
import hmac
import json
import urllib.request

from django.conf import settings

ORDERS_URL = "https://api.razorpay.com/v1/orders"


def create_order(amount_paise, receipt):
    """Create an order for `amount_paise` and return its id. Raises OSError/ValueError/KeyError on failure."""
    credentials = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    request = urllib.request.Request(
        ORDERS_URL,
        data=json.dumps({"amount": amount_paise, "currency": "INR", "receipt": receipt}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(credentials).decode(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["id"]


def _signed(secret, message, signature):
    if not secret:  # an empty secret would let anyone forge a signature
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def payment_signature_ok(order_id, payment_id, signature):
    """Checkout's success callback: HMAC-SHA256 of "order_id|payment_id" with the key secret."""
    return _signed(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode(), signature)


def webhook_signature_ok(body, signature):
    """Webhook: HMAC-SHA256 of the raw body with the webhook secret."""
    return _signed(settings.RAZORPAY_WEBHOOK_SECRET, body, signature)
