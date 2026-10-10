from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Customer


class PhoneForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["phone"]
        labels = {"phone": "Your mobile number"}
        help_texts = {"phone": "So the café can reach you about a booking. 10 digits, no +91."}
        widgets = {"phone": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "tel-national"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].required = True


@login_required
def phone(request):
    customer, _ = Customer.objects.get_or_create(user=request.user)
    next_url = request.GET.get("next", "/")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = "/"
    form = PhoneForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(next_url)
    return render(request, "booking/phone.html", {"form": form})
