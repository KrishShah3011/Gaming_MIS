import json

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from status.models import CafeSettings

from . import razorpay, services
from .auth import customer_required
from .models import Offer, TopUpOrder


@customer_required
def wallet(request):
    now, cafe = timezone.now(), CafeSettings.load()
    balance = services.balance_paise(request.customer)
    return render(request, "booking/wallet.html", {
        "balance": balance,
        "hours": balance / (cafe.hourly_rate_rupees * 100),
        "offers": services.live_offers(now, cafe),
        "entries": request.customer.wallet_entries.select_related("booking__pc")[:50],
        "min_rupees": services.TOPUP_MIN_RUPEES,
        "max_rupees": services.TOPUP_MAX_RUPEES,
        "razorpay_key": settings.RAZORPAY_KEY_ID,
    })


def _error(text, status=400):
    return JsonResponse({"error": text}, status=status)


@require_POST
@customer_required
def topup_order(request):
    now, offer = timezone.now(), None
    offer_id, amount = request.POST.get("offer", ""), request.POST.get("amount", "")
    if offer_id:
        offer = Offer.objects.filter(pk=offer_id).first() if offer_id.isdigit() else None
        if offer is None:
            return _error("That offer has ended. Pick another amount.")
    elif not amount.isdigit():
        return _error(f"Enter an amount between ₹{services.TOPUP_MIN_RUPEES} and ₹{services.TOPUP_MAX_RUPEES:,}.")
    try:
        amount_paise, bonus_paise, offer = services.topup_terms(int(amount or 0), offer, now)
    except services.BookingError as error:
        return _error(str(error))
    try:
        order_id = razorpay.create_order(amount_paise, receipt=f"c{request.customer.pk}-{int(now.timestamp())}")
    except (OSError, ValueError, KeyError):
        return _error("Payments aren't available right now. Try again in a minute.", status=502)
    TopUpOrder.objects.create(razorpay_order_id=order_id, customer=request.customer,
                              amount_paise=amount_paise, bonus_paise=bonus_paise, offer=offer)
    user = request.user
    return JsonResponse({
        "order_id": order_id, "amount": amount_paise, "key": settings.RAZORPAY_KEY_ID,
        "name": CafeSettings.load().cafe_name,
        "prefill": {"name": user.get_full_name(), "email": user.email, "contact": request.customer.phone},
    })


@require_POST
@customer_required
def topup_paid(request):
    """Razorpay Checkout's success callback, relayed by the wallet page."""
    order_id = request.POST.get("razorpay_order_id", "")
    payment_id = request.POST.get("razorpay_payment_id", "")
    order = TopUpOrder.objects.filter(razorpay_order_id=order_id, customer=request.customer).first()
    if order is None or not razorpay.payment_signature_ok(order_id, payment_id, request.POST.get("razorpay_signature", "")):
        return _error("We couldn't confirm that payment. If money left your account, it will appear here within a few minutes.")
    services.credit_topup(order, payment_id, timezone.now())
    messages.success(request, "Payment received. Your balance is updated.")
    return JsonResponse({"ok": True})


@csrf_exempt  # protected by the signature instead
@require_POST
def razorpay_webhook(request):
    if not razorpay.webhook_signature_ok(request.body, request.headers.get("X-Razorpay-Signature", "")):
        return _error("bad signature")
    try:
        event = json.loads(request.body)
        payment = event["payload"]["payment"]["entity"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": True})  # signed, but not a payment event: nothing to do
    if event.get("event") == "payment.captured":
        order = TopUpOrder.objects.filter(razorpay_order_id=payment.get("order_id")).first()
        if order is not None and payment.get("amount") == order.amount_paise:
            services.credit_topup(order, payment["id"], timezone.now())
    return JsonResponse({"ok": True})  # 200 so Razorpay doesn't retry
