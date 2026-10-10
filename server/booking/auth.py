from functools import wraps
from urllib.parse import urlencode

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse

from .models import Customer


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False  # no password sign-ups: customers join through Google


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True


def customer_required(view):
    """Signed in, with a Customer row and a phone number on file. Sets request.customer."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        customer, _ = Customer.objects.get_or_create(user=request.user)
        if not customer.phone:
            return redirect(f"{reverse('phone')}?{urlencode({'next': request.get_full_path()})}")
        request.customer = customer
        return view(request, *args, **kwargs)

    return wrapper
