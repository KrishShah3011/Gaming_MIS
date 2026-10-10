from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from booking.auth import customer_required
from booking.models import Customer
from booking.templatetags.booking_extras import duration, rupees
from status.models import CafeSettings


class SignInTests(TestCase):
    def test_login_page_offers_google_only(self):
        response = self.client.get("/accounts/login/?next=/me/phone/")
        self.assertContains(response, "Sign in with Google")
        self.assertContains(response, 'action="/accounts/google/login/')
        self.assertNotContains(response, 'name="password"')

    def test_password_signup_is_closed(self):
        self.client.post("/accounts/signup/", {"email": "x@example.com", "password1": "pw-123456789x", "password2": "pw-123456789x"})
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    def test_customer_required_asks_for_phone_once(self):
        user = User.objects.create_user("asha")
        request = RequestFactory().get("/me/wallet/")
        request.user = user
        view = customer_required(lambda request: HttpResponse(request.customer.user.username))
        response = view(request)
        self.assertEqual((response.status_code, response["Location"]), (302, "/me/phone/?next=%2Fme%2Fwallet%2F"))
        Customer.objects.filter(user=user).update(phone="9876543210")
        self.assertEqual(view(request).content, b"asha")

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertRedirects(self.client.get("/me/phone/"), "/accounts/login/?next=/me/phone/", fetch_redirect_response=False)


class PhoneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("asha")
        self.client.force_login(self.user)

    def test_saves_phone_and_returns(self):
        response = self.client.post("/me/phone/?next=/me/wallet/", {"phone": "9876543210"})
        self.assertRedirects(response, "/me/wallet/", fetch_redirect_response=False)
        self.assertEqual(Customer.objects.get(user=self.user).phone, "9876543210")

    def test_rejects_bad_number(self):
        response = self.client.post("/me/phone/", {"phone": "12345"})
        self.assertContains(response, "Enter a 10-digit Indian mobile number.")

    def test_ignores_offsite_next(self):
        response = self.client.post("/me/phone/?next=https://evil.example/", {"phone": "9876543210"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class PolicyPageTests(TestCase):
    def test_pages_show_cafe_details(self):
        cafe = CafeSettings.load()
        cafe.cafe_name, cafe.contact_phone = "Night Owl Gaming", "9876543210"
        cafe.save()
        for path in ("/terms/", "/privacy/", "/refunds/", "/contact/"):
            self.assertContains(self.client.get(path), "Night Owl Gaming")
        self.assertContains(self.client.get("/contact/"), "9876543210")


class FilterTests(TestCase):
    def test_rupees(self):
        self.assertEqual([rupees(12500), rupees(2475), rupees(-15000), rupees(0)], ["₹125", "₹24.75", "−₹150", "₹0"])
        self.assertEqual(rupees(1000000), "₹10,000")

    def test_duration(self):
        self.assertEqual([duration(60), duration(90), duration(30), duration(120)], ["1 hr", "1 hr 30 min", "30 min", "2 hrs"])
