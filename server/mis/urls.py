from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("staff/login/", auth_views.LoginView.as_view(next_page="dashboard"), name="login"),
    path("staff/logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("accounts/", include("allauth.urls")),
    path("", include("booking.urls")),
    path("", include("status.urls")),
]
