import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from booking import services
from booking.models import Offer, TopUpOrder

from .helpers import make_customer


def payment_signature(order_id, payment_id):
    return hmac.new(b"secret", f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET="secret", RAZORPAY_WEBHOOK_SECRET="hook")
class WalletTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.client.force_login(self.customer.user)
        self.offer = Offer.objects.create(name="Pay 500, get 6 hrs", pay_rupees=500, bonus_rupees=100)

    def balance(self):
        return services.balance_paise(self.customer)

    def test_wallet_page(self):
        response = self.client.get("/me/wallet/")
        self.assertContains(response, "₹0")
        self.assertContains(response, "Pay ₹500, get ₹600")
        self.assertContains(response, "Top up ₹500")

    @patch("booking.razorpay.create_order", return_value="order_1")
    def test_order_amount_comes_from_the_server(self, create_order):
        response = self.client.post("/me/wallet/order", {"offer": self.offer.pk, "amount": "1"})
        self.assertEqual(response.json()["amount"], 50000)
        self.assertEqual(response.json()["order_id"], "order_1")
        order = TopUpOrder.objects.get()
        self.assertEqual((order.amount_paise, order.bonus_paise, order.customer), (50000, 10000, self.customer))
        self.assertEqual(create_order.call_args.args[0], 50000)

    @patch("booking.razorpay.create_order", return_value="order_1")
    def test_order_limits_and_bad_input(self, create_order):
        for data in ({"amount": "50"}, {"amount": "abc"}, {"offer": "abc"}, {"offer": "999"}):
            response = self.client.post("/me/wallet/order", data)
            self.assertEqual(response.status_code, 400, data)
            self.assertIn("error", response.json())
        create_order.assert_not_called()

    @patch("booking.razorpay.create_order", side_effect=OSError("down"))
    def test_order_when_razorpay_is_down(self, create_order):
        response = self.client.post("/me/wallet/order", {"amount": "200"})
        self.assertEqual(response.status_code, 502)
        self.assertFalse(TopUpOrder.objects.exists())

    def make_order(self, customer=None):
        return TopUpOrder.objects.create(razorpay_order_id="order_1", customer=customer or self.customer,
                                         amount_paise=50000, bonus_paise=10000, offer=self.offer)

    def paid(self, payment_id="pay_1", signature=None):
        return self.client.post("/me/wallet/paid", {
            "razorpay_order_id": "order_1", "razorpay_payment_id": payment_id,
            "razorpay_signature": signature or payment_signature("order_1", payment_id),
        })

    def test_paid_callback_credits_once(self):
        self.make_order()
        self.assertEqual(self.paid().status_code, 200)
        self.paid()
        self.assertEqual(self.balance(), 60000)

    def test_paid_callback_with_bad_signature(self):
        self.make_order()
        self.assertEqual(self.paid(signature="nope").status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_cannot_claim_another_customers_order(self):
        self.make_order(customer=make_customer("ravi"))
        self.assertEqual(self.paid().status_code, 400)

    def webhook(self, payment_id="pay_1", amount=50000, signature=None):
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": "order_1", "amount": amount}}}}).encode()
        return Client().post("/payments/razorpay/webhook", body, content_type="application/json",
                             HTTP_X_RAZORPAY_SIGNATURE=signature or hmac.new(b"hook", body, hashlib.sha256).hexdigest())

    def test_webhook_then_callback_credits_once(self):
        self.make_order()
        self.assertEqual(self.webhook().status_code, 200)
        self.assertEqual(self.balance(), 60000)
        self.paid()
        self.assertEqual(self.balance(), 60000)

    def test_webhook_bad_signature(self):
        self.make_order()
        self.assertEqual(self.webhook(signature="nope").status_code, 400)
        self.assertEqual(self.balance(), 0)

    def test_webhook_amount_mismatch_credits_nothing(self):
        self.make_order()
        self.assertEqual(self.webhook(amount=100).status_code, 200)
        self.assertEqual(self.balance(), 0)

    def test_history_shows_entries(self):
        self.make_order()
        self.paid()
        response = self.client.get("/me/wallet/")
        self.assertContains(response, "Online top-up")
        self.assertContains(response, "Offer bonus")
        self.assertContains(response, "₹600")
