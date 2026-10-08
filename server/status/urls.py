from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("api/v1/heartbeat", views.heartbeat, name="heartbeat"),
]
