# views.py
# Mini Hospital Management System – Core Views
# ============================================================
# Covers:
#   • Session-based authentication (login / logout / signup)
#   • Patient booking view with select_for_update() concurrency guard
#   • Email notification trigger (calls Serverless Lambda via HTTP POST)
# ============================================================
import os
import google_auth_oauthlib.flow
from django.shortcuts import redirect
from django.http import HttpResponse
import logging
from .utils import trigger_hospital_email
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt   # only during dev; use CSRF tokens in prod

from .models import Availability, Booking, User
from .services import create_google_calendar_event     # Google Calendar utility
from .notifications import send_notification           # Serverless email trigger helper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper decorator: enforce patient role
# ---------------------------------------------------------------------------

def patient_required(view_func):
    """Decorator that rejects non-patient users with a 403 response."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_patient:
            return JsonResponse({"error": "Only patients can perform this action."}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Auth Views
# ---------------------------------------------------------------------------

@csrf_exempt
def signup_view(request):
    """
    POST /auth/signup/
    Body (JSON): { email, username, password, first_name, last_name,
                   role: "doctor" | "patient" }

    Creates a new user and sends a SIGNUP_WELCOME email via the Lambda microservice.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    email      = data.get("email", "").strip().lower()
    username   = data.get("username", "").strip()
    password   = data.get("password", "")
    first_name = data.get("first_name", "").strip()
    last_name  = data.get("last_name", "").strip()
    role       = data.get("role", "")   # "doctor" or "patient"

    # --- Basic validation ---
    if not all([email, username, password, role]):
        return JsonResponse({"error": "email, username, password, and role are required."}, status=400)
    if role not in ("doctor", "patient"):
        return JsonResponse({"error": "role must be 'doctor' or 'patient'."}, status=400)
    if User.objects.filter(email=email).exists():
        return JsonResponse({"error": "A user with this email already exists."}, status=409)

    try:
        user = User.objects.create_user(
            email      = email,
            username   = username,
            password   = password,
            first_name = first_name,
            last_name  = last_name,
            is_doctor  = (role == "doctor"),
            is_patient = (role == "patient"),
        )
    except Exception as exc:
        logger.exception("Signup failed: %s", exc)
        return JsonResponse({"error": "Could not create user. Please try again."}, status=500)

    # Fire-and-forget: trigger SIGNUP_WELCOME email via Lambda microservice.
    send_notification(
        email_type="SIGNUP_WELCOME",
        recipient_email=user.email,
        details={
            "first_name": user.first_name or user.username,
            "role": role,
        },
    )

    return JsonResponse({"message": "Account created successfully.", "user_id": user.pk}, status=201)


@csrf_exempt
def login_view(request):
    """
    POST /auth/login/
    Body (JSON): { email, password }

    Authenticates the user and creates a server-side session.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = authenticate(request, email=email, password=password)
    if user is None:
        return JsonResponse({"error": "Invalid credentials."}, status=401)
    if not user.is_active:
        return JsonResponse({"error": "Account is disabled."}, status=403)

    login(request, user)
    return JsonResponse({
        "message": "Login successful.",
        "user": {
            "id":         user.pk,
            "email":      user.email,
            "username":   user.username,
            "is_doctor":  user.is_doctor,
            "is_patient": user.is_patient,
        }
    })


@login_required
def logout_view(request):
    """POST /auth/logout/  – Destroys the current session."""
    logout(request)
    return JsonResponse({"message": "Logged out successfully."})


# ---------------------------------------------------------------------------
# Booking View  ← CORE: concurrency-safe slot booking
# ---------------------------------------------------------------------------

@method_decorator([csrf_exempt, patient_required], name="dispatch")
class BookSlotView(View):
    """
    POST /bookings/
    Body (JSON): { availability_id: <int>, notes: "<optional string>" }

    Books an availability slot for the authenticated patient.

    Concurrency guarantee
    ─────────────────────
    We wrap the critical section in `transaction.atomic()` and lock the
    target Availability row with `select_for_update()`.

    Timeline when two patients (P1, P2) race for the same slot:
      T1 – P1 enters atomic block, acquires row-level lock on Availability.
      T2 – P2 enters atomic block, blocks on `select_for_update()` (waits for lock).
      T3 – P1 sees is_booked=False → creates Booking, sets is_booked=True → commits.
      T4 – P2 acquires lock, re-reads row → now sees is_booked=True → returns 409.

    This eliminates the TOCTOU race condition that would exist if we used a
    plain .get() + conditional check without locking.
    """

    def post(self, request, *args, **kwargs):
        import json
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        availability_id = data.get("availability_id")
        notes           = data.get("notes", "").strip()

        if not availability_id:
            return JsonResponse({"error": "availability_id is required."}, status=400)

        patient = request.user

        # ── Begin atomic, serialised section ──────────────────────────────
        try:
            with transaction.atomic():
                # -----------------------------------------------------------
                # STEP 1: Lock the row.
                # `select_for_update()` issues a SELECT … FOR UPDATE which
                # acquires a row-level exclusive lock in PostgreSQL.
                # Any concurrent transaction attempting to lock the same row
                # will BLOCK here until we commit or rollback.
                # -----------------------------------------------------------
                try:
                    availability = (
                        Availability.objects
                        .select_for_update()          # ← THE LOCK
                        .select_related("doctor")     # fetch doctor in same query
                        .get(pk=availability_id)
                    )
                except Availability.DoesNotExist:
                    return JsonResponse(
                        {"error": "Availability slot not found."},
                        status=404,
                    )

                # -----------------------------------------------------------
                # STEP 2: Re-check availability AFTER acquiring the lock.
                # The state we read NOW is authoritative (no stale read).
                # -----------------------------------------------------------
                if availability.is_booked:
                    return JsonResponse(
                        {
                            "error": (
                                "This slot has just been booked by another patient. "
                                "Please choose a different time."
                            )
                        },
                        status=409,   # 409 Conflict
                    )

                # -----------------------------------------------------------
                # STEP 3: Check the patient doesn't already have a confirmed
                # booking that overlaps this slot (optional business rule).
                # -----------------------------------------------------------
                overlapping_own_booking = Booking.objects.filter(
                    patient=patient,
                    status=Booking.Status.CONFIRMED,
                    availability__date=availability.date,
                    availability__start_time__lt=availability.end_time,
                    availability__end_time__gt=availability.start_time,
                ).exists()

                if overlapping_own_booking:
                    return JsonResponse(
                        {"error": "You already have a confirmed booking that overlaps this slot."},
                        status=409,
                    )

                # -----------------------------------------------------------
                # STEP 4: Create the booking and mark the slot as booked.
                # Both writes happen atomically – either both commit or both
                # roll back (e.g. if Google Calendar API raises an exception).
                # -----------------------------------------------------------
                booking = Booking.objects.create(
                    patient      = patient,
                    availability = availability,
                    notes        = notes,
                    status       = Booking.Status.CONFIRMED,
                )

                availability.is_booked = True
                availability.save(update_fields=["is_booked", "updated_at"])

                # -----------------------------------------------------------
                # STEP 5: Create Google Calendar events.
                # Wrapped in try/except so a Calendar API failure doesn't
                # roll back the booking – we log the error and continue.
                # -----------------------------------------------------------
                try:
                    event_ids = create_google_calendar_event(booking)
                    if event_ids:
                        booking.doctor_event_id  = event_ids.get("doctor_event_id")
                        booking.patient_event_id = event_ids.get("patient_event_id")
                        booking.save(update_fields=["doctor_event_id", "patient_event_id"])
                except Exception as cal_exc:
                    logger.error(
                        "Google Calendar event creation failed for Booking #%s: %s",
                        booking.pk, cal_exc, exc_info=True,
                    )
                # ── End atomic block ─────────────────────────────────────────

        except IntegrityError as e:
            # Handles the DB-level unique constraint on Booking ↔ Availability.
            logger.warning("IntegrityError during booking (possible race): %s", e)
            return JsonResponse(
                {"error": "This slot has already been booked. Please select another."},
                status=409,
            )
        except Exception as exc:
            logger.exception("Unexpected error during booking: %s", exc)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)

        # -------------------------------------------------------------------
        # STEP 6: Trigger BOOKING_CONFIRMATION email (outside the DB tx).
        # Fire-and-forget: if Lambda is down the booking is still saved.
        # -------------------------------------------------------------------
        doctor  = availability.doctor
        _trigger_booking_emails(booking, doctor, patient, availability)

        return JsonResponse(
            {
                "message": "Booking confirmed successfully!",
                "booking": {
                    "id":              booking.pk,
                    "status":          booking.status,
                    "date":            str(availability.date),
                    "start_time":      str(availability.start_time),
                    "end_time":        str(availability.end_time),
                    "doctor":          doctor.get_full_name(),
                    "patient":         patient.get_full_name(),
                    "doctor_event_id": booking.doctor_event_id,
                    "patient_event_id":booking.patient_event_id,
                },
            },
            status=201,
        )


def _trigger_booking_emails(booking, doctor, patient, availability):
    """
    Helper: sends BOOKING_CONFIRMATION emails to both doctor and patient
    via the Serverless Lambda HTTP endpoint (serverless-offline on :3000).
    """
    shared_details = {
        "booking_id": booking.pk,
        "date":       str(availability.date),
        "start_time": str(availability.start_time),
        "end_time":   str(availability.end_time),
        "doctor_name": f"Dr. {doctor.get_full_name()}",
        "patient_name": patient.get_full_name(),
    }

    # Email to patient
    send_notification(
        email_type="BOOKING_CONFIRMATION",
        recipient_email=patient.email,
        details={**shared_details, "recipient_role": "patient"},
    )

    # Email to doctor
    send_notification(
        email_type="BOOKING_CONFIRMATION",
        recipient_email=doctor.email,
        details={**shared_details, "recipient_role": "doctor"},
    )
    
# ---------------------------------------------------------------------------
# Google Calendar OAuth2 Views
# ---------------------------------------------------------------------------

# Security setting strictly for local testing (Do not use in production!)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Locates the credentials.json file you downloaded earlier
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'credentials.json')

def google_auth_redirect(request):
    """Bounces the doctor/patient to the Google Login Screen"""
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events']
    )
    flow.redirect_uri = 'http://localhost:8000/oauth2callback'
    
    # Force Google to give us a refresh token
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )
    
    # SAVE the state AND the new code_verifier to Django's session memory
    request.session['state'] = state
    request.session['code_verifier'] = flow.code_verifier
    
    return redirect(authorization_url)


def google_auth_callback(request):
    """Google sends the user back here with the secret tokens"""
    state = request.session.get('state')
    code_verifier = request.session.get('code_verifier')
    
    if not state or not code_verifier:
        return HttpResponse("Session expired or invalid state. Try logging in again.", status=400)
        
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        state=state
    )
    flow.redirect_uri = 'http://localhost:8000/oauth2callback'
    
    # RESTORE the code verifier we saved before sending them to Google
    flow.code_verifier = code_verifier
    
    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)
    
    credentials = flow.credentials
    
    # Save these tokens directly to the logged-in user!
    if request.user.is_authenticated:
        request.user.google_access_token = credentials.token
        request.user.google_refresh_token = credentials.refresh_token
        request.user.save()
        return HttpResponse("✅ Success! Google Calendar is now linked to your account. You can close this window and book an appointment!")
    else:
        return HttpResponse("❌ Error: You must be logged into the Hospital system first before linking Google.", status=403)