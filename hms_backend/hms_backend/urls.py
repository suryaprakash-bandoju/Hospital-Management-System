from django.contrib import admin
from django.urls import path
from booking import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Auth
    path("auth/signup/",  views.signup_view,  name="signup"),
    path("auth/login/",   views.login_view,   name="login"),
    path("auth/logout/",  views.logout_view,  name="logout"),

    # Google OAuth2 (Fixed to match Google Console exactly!)
    path("auth/google/", views.google_auth_redirect, name="google_auth"),
    path("oauth2callback/", views.google_auth_callback, name="google_callback"),

    # Bookings
    path("bookings/", views.BookSlotView.as_view(), name="book_slot"),
]