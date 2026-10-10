from django.urls import path
from django.views.generic import TemplateView

from . import views


def policy(name):
    return path(f"{name}/", TemplateView.as_view(template_name=f"booking/policies/{name}.html"), name=name)


urlpatterns = [
    path("me/phone/", views.phone, name="phone"),
    policy("terms"),
    policy("privacy"),
    policy("refunds"),
    policy("contact"),
]
