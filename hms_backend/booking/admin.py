from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Availability, Booking

# Register your custom models so they show up in the dashboard
admin.site.register(User, UserAdmin)
admin.site.register(Availability)
admin.site.register(Booking)