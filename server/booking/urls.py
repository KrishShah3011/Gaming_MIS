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
    path("me/bookings/", views.my_bookings, name="bookings"),
    path("me/bookings/<int:pk>/cancel", views.cancel_booking, name="cancel_booking"),
    path("me/bookings/<int:pk>/extend", views.extend_booking, name="extend_booking"),
    path("me/wallet/", wallet_views.wallet, name="wallet"),
    path("me/wallet/order", wallet_views.topup_order, name="topup_order"),
    path("me/wallet/paid", wallet_views.topup_paid, name="topup_paid"),
    path("staff/bookings/<int:pk>/clear", views.clear_booking, name="clear_booking"),
    path("payments/razorpay/webhook", wallet_views.razorpay_webhook, name="razorpay_webhook"),
    policy("terms"),
    policy("privacy"),
    policy("refunds"),
    policy("contact"),
]
