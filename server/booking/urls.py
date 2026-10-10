from django.urls import path
from django.views.generic import TemplateView

from . import views, wallet_views


def policy(name):
    return path(f"{name}/", TemplateView.as_view(template_name=f"booking/policies/{name}.html"), name=name)


urlpatterns = [
    path("", views.home, name="home"),
    path("book/", views.book, name="book"),
    path("book/<uuid:group>/", views.ticket, name="ticket"),
    path("me/phone/", views.phone, name="phone"),
    path("me/wallet/", wallet_views.wallet, name="wallet"),
    path("me/wallet/order", wallet_views.topup_order, name="topup_order"),
    path("me/wallet/paid", wallet_views.topup_paid, name="topup_paid"),
    path("payments/razorpay/webhook", wallet_views.razorpay_webhook, name="razorpay_webhook"),
    policy("terms"),
    policy("privacy"),
    policy("refunds"),
    policy("contact"),
]
