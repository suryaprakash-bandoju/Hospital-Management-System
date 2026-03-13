# models.py
# Mini Hospital Management System - Django Models
# ============================================================
# Covers: Custom User, Availability (with overlap constraints),
#         and Booking models.
# ============================================================

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


# ---------------------------------------------------------------------------
# Custom User Manager
# ---------------------------------------------------------------------------

class UserManager(BaseUserManager):
    """Manager for the custom User model supporting doctor/patient roles."""

    def _create_user(self, email, username, password, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")
        if not username:
            raise ValueError("The Username field must be set.")
        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, username, password, **extra_fields)

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_doctor", False)
        extra_fields.setdefault("is_patient", False)
        return self._create_user(email, username, password, **extra_fields)


# ---------------------------------------------------------------------------
# Custom User Model
# ---------------------------------------------------------------------------

class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model that supports two distinct roles:
      - is_doctor  : Can create availability slots and receive bookings.
      - is_patient : Can browse available slots and create bookings.

    A user MUST have exactly one of these roles (enforced at the form/serialiser
    layer; the model itself stores both flags for flexibility).
    """

    email       = models.EmailField(unique=True, db_index=True)
    username    = models.CharField(max_length=150, unique=True)
    first_name  = models.CharField(max_length=150, blank=True)
    last_name   = models.CharField(max_length=150, blank=True)
    phone       = models.CharField(max_length=20, blank=True)

    # --- Role flags ---
    is_doctor   = models.BooleanField(default=False, help_text="Designates this user as a doctor.")
    is_patient  = models.BooleanField(default=False, help_text="Designates this user as a patient.")

    # --- Django internals ---
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # --- Google OAuth tokens (stored per user for Calendar API) ---
    google_access_token   = models.TextField(blank=True, null=True)
    google_refresh_token  = models.TextField(blank=True, null=True)
    google_token_expiry   = models.DateTimeField(blank=True, null=True)
    google_calendar_id    = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="The user's primary Google Calendar ID (usually their email)."
    )

    objects = UserManager()

    USERNAME_FIELD  = "email"        # Login via email
    REQUIRED_FIELDS = ["username"]   # Required when using createsuperuser

    class Meta:
        verbose_name        = "User"
        verbose_name_plural = "Users"
        constraints = [
            # A user cannot be both a doctor AND a patient simultaneously.
            models.CheckConstraint(
                condition=~(models.Q(is_doctor=True) & models.Q(is_patient=True)),
                name="user_cannot_be_both_doctor_and_patient",
            )
        ]

    def __str__(self):
        role = "Doctor" if self.is_doctor else ("Patient" if self.is_patient else "Admin")
        return f"{self.get_full_name()} ({role}) <{self.email}>"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def get_short_name(self):
        return self.first_name or self.username


# ---------------------------------------------------------------------------
# Availability Model
# ---------------------------------------------------------------------------

class Availability(models.Model):
    """
    Represents a time slot that a doctor has opened for appointments.

    Constraints enforced:
      1. A doctor cannot have two slots with the EXACT same (date, start_time, end_time).
      2. A doctor cannot have OVERLAPPING slots on the same date
         (enforced via clean() + a DB-level UniqueConstraint for the exact-match case).
    """

    doctor      = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="availabilities",
        limit_choices_to={"is_doctor": True},
    )
    date        = models.DateField(help_text="Calendar date of this availability slot.")
    start_time  = models.TimeField(help_text="Slot start time (local time).")
    end_time    = models.TimeField(help_text="Slot end time (local time).")
    is_booked   = models.BooleanField(
        default=False,
        help_text="True once a patient has confirmed a booking for this slot.",
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Availability"
        verbose_name_plural = "Availabilities"
        ordering            = ["date", "start_time"]
        constraints = [
            # DB-level guard against exact duplicates (same doctor, date, start, end).
            models.UniqueConstraint(
                fields=["doctor", "date", "start_time", "end_time"],
                name="unique_doctor_slot",
            )
        ]
        indexes = [
            models.Index(fields=["doctor", "date", "is_booked"]),
        ]

    # ------------------------------------------------------------------
    # Validation – overlap detection (runs before save via full_clean)
    # ------------------------------------------------------------------

    def clean(self):
        """
        Prevent a doctor from creating a slot that overlaps with any of their
        existing slots on the same date.

        Overlap condition (A = existing slot, B = new slot):
            A.start_time < B.end_time  AND  A.end_time > B.start_time
        """
        super().clean()

        if self.start_time >= self.end_time:
            raise ValidationError("start_time must be strictly before end_time.")

        # Build the queryset of potentially overlapping slots for this doctor/date.
        overlapping_qs = Availability.objects.filter(
            doctor=self.doctor,
            date=self.date,
            start_time__lt=self.end_time,   # existing slot starts before new slot ends
            end_time__gt=self.start_time,    # existing slot ends   after new slot starts
        )

        # Exclude the current instance when updating an existing record.
        if self.pk:
            overlapping_qs = overlapping_qs.exclude(pk=self.pk)

        if overlapping_qs.exists():
            raise ValidationError(
                f"This slot overlaps with an existing availability slot for "
                f"Dr. {self.doctor.get_full_name()} on {self.date}."
            )

    def save(self, *args, **kwargs):
        # Always run full model validation before persisting.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        status = "Booked" if self.is_booked else "Available"
        return (
            f"Dr. {self.doctor.get_full_name()} | {self.date} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M} [{status}]"
        )


# ---------------------------------------------------------------------------
# Booking Model
# ---------------------------------------------------------------------------

class Booking(models.Model):
    """
    Records a confirmed appointment between a patient and a doctor's
    availability slot.

    Key rules:
      • One Booking per Availability slot (OneToOne).
      • Only patients may create bookings (enforced at view layer).
      • status tracks the lifecycle of the appointment.
    """

    class Status(models.TextChoices):
        CONFIRMED  = "confirmed",  "Confirmed"
        CANCELLED  = "cancelled",  "Cancelled"
        COMPLETED  = "completed",  "Completed"
        NO_SHOW    = "no_show",    "No Show"

    patient         = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bookings",
        limit_choices_to={"is_patient": True},
    )
    availability    = models.OneToOneField(
        Availability,
        on_delete=models.CASCADE,
        related_name="booking",
        help_text="The specific availability slot being booked.",
    )
    status          = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    notes           = models.TextField(
        blank=True,
        help_text="Optional notes from the patient (symptoms, reason for visit, etc.).",
    )
    # Google Calendar event IDs stored after successful calendar creation.
    doctor_event_id  = models.CharField(max_length=255, blank=True, null=True)
    patient_event_id = models.CharField(max_length=255, blank=True, null=True)

    booked_at       = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Booking"
        verbose_name_plural = "Bookings"
        ordering            = ["-booked_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
        ]

    def __str__(self):
        return (
            f"Booking #{self.pk} | Patient: {self.patient.get_full_name()} | "
            f"Dr. {self.availability.doctor.get_full_name()} | "
            f"{self.availability.date} {self.availability.start_time:%H:%M} "
            f"[{self.status}]"
        )
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .utils import trigger_hospital_email  # Importing your helper function!

User = get_user_model()

@receiver(post_save, sender=User)
def send_welcome_email(sender, instance, created, **kwargs):
    # 'created' is True only if this is a brand new user, not an edit
    if created and instance.email:
        print(f"🔔 Database Signal Caught! Firing email to {instance.email}...")
        
        # Grab their first name, or fallback to their username if name is blank
        name = instance.first_name if instance.first_name else instance.username
        
        trigger_hospital_email(
            email_type="SIGNUP_WELCOME",
            recipient_email=instance.email,
            patient_name=name
        )
