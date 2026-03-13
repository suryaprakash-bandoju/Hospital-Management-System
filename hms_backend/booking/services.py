# services.py
# Mini Hospital Management System – Google Calendar Integration
# ============================================================
# Uses the Google Calendar API (OAuth2) to create calendar events
# for confirmed bookings on both the doctor's and patient's calendars.
#
# Prerequisites (pip install):
#   google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
#
# Django settings required:
#   GOOGLE_CLIENT_ID        – OAuth2 client ID
#   GOOGLE_CLIENT_SECRET    – OAuth2 client secret
#   GOOGLE_REDIRECT_URI     – Authorised redirect URI
#   GOOGLE_SCOPES           – ["https://www.googleapis.com/auth/calendar.events"]
# ============================================================

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_credentials(user) -> Credentials | None:
    """
    Reconstruct a google.oauth2.credentials.Credentials object from the
    tokens stored on the User model.

    Returns None if the user has not connected their Google account.
    """
    if not user.google_refresh_token:
        logger.warning(
            "User %s (%s) has no Google refresh token – cannot access Calendar API.",
            user.pk, user.email,
        )
        return None

    creds = Credentials(
        token         = user.google_access_token,
        refresh_token = user.google_refresh_token,
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = settings.GOOGLE_CLIENT_ID,
        client_secret = settings.GOOGLE_CLIENT_SECRET,
        scopes        = settings.GOOGLE_SCOPES,
    )

    # Refresh access token if it has expired (google-auth handles this automatically).
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Persist the new access token so we don't refresh on every request.
            user.google_access_token  = creds.token
            user.google_token_expiry  = creds.expiry
            user.save(update_fields=["google_access_token", "google_token_expiry"])
        except Exception as exc:
            logger.error("Failed to refresh Google token for user %s: %s", user.pk, exc)
            return None

    return creds


def _slot_to_rfc3339(date_obj, time_obj) -> str:
    """
    Combine a date and a time (both naive, assumed local time in the
    GOOGLE_CALENDAR_TIMEZONE setting) into an RFC-3339 datetime string
    that the Calendar API expects.
    """
    tz_str   = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "UTC")
    # Build a naive datetime then let Google interpret it with the given tz.
    combined = datetime.combine(date_obj, time_obj)
    # Return ISO format; the 'timeZone' key in the event body carries tz info.
    return combined.strftime("%Y-%m-%dT%H:%M:%S")


def _create_event_for_user(service, calendar_id: str, event_body: dict) -> str | None:
    """
    Insert an event into the given Google Calendar.
    Returns the created event ID, or None on failure.
    """
    try:
        created_event = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
        event_id = created_event.get("id")
        logger.info("Created Google Calendar event %s on calendar %s", event_id, calendar_id)
        return event_id
    except HttpError as exc:
        logger.error(
            "Google Calendar API error (calendar=%s, status=%s): %s",
            calendar_id, exc.status_code, exc.error_details,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_google_calendar_event(booking) -> dict | None:
    """
    Create Google Calendar events for a confirmed booking on both the
    doctor's and the patient's calendars.

    Parameters
    ----------
    booking : Booking
        A saved Booking instance with `availability` and related
        `patient` / `doctor` pre-fetched (or accessible via FK).

    Returns
    -------
    dict | None
        { "doctor_event_id": str, "patient_event_id": str }
        or None if both event creations fail.
    """
    availability = booking.availability
    doctor       = availability.doctor
    patient      = booking.patient

    tz_str       = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "UTC")
    start_str    = _slot_to_rfc3339(availability.date, availability.start_time)
    end_str      = _slot_to_rfc3339(availability.date, availability.end_time)

    results = {}

    # ── 1. Doctor's calendar ──────────────────────────────────────────────
    doctor_creds = _build_credentials(doctor)
    if doctor_creds:
        doctor_service = build("calendar", "v3", credentials=doctor_creds)
        doctor_calendar_id = doctor.google_calendar_id or "primary"

        doctor_event_body = {
            # Title: "Appointment with <PatientName>"
            "summary": f"Appointment with {patient.get_full_name()}",
            "description": (
                f"Patient: {patient.get_full_name()}\n"
                f"Email: {patient.email}\n"
                f"Phone: {patient.phone or 'N/A'}\n"
                f"Notes: {booking.notes or 'None'}\n"
                f"Booking ID: #{booking.pk}"
            ),
            "start": {
                "dateTime": start_str,
                "timeZone": tz_str,
            },
            "end": {
                "dateTime": end_str,
                "timeZone": tz_str,
            },
            "attendees": [
                {"email": doctor.email,  "displayName": f"Dr. {doctor.get_full_name()}"},
                {"email": patient.email, "displayName": patient.get_full_name()},
            ],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},   # 1 hour before
                    {"method": "popup",  "minutes": 15},   # 15 minutes before
                ],
            },
            "status": "confirmed",
        }

        results["doctor_event_id"] = _create_event_for_user(
            doctor_service, doctor_calendar_id, doctor_event_body
        )
    else:
        logger.warning("Skipping doctor calendar event – no valid credentials for user %s.", doctor.pk)

    # ── 2. Patient's calendar ─────────────────────────────────────────────
    patient_creds = _build_credentials(patient)
    if patient_creds:
        patient_service = build("calendar", "v3", credentials=patient_creds)
        patient_calendar_id = patient.google_calendar_id or "primary"

        patient_event_body = {
            # Title: "Appointment with Dr. <DoctorName>"
            "summary": f"Appointment with Dr. {doctor.get_full_name()}",
            "description": (
                f"Doctor: Dr. {doctor.get_full_name()}\n"
                f"Email: {doctor.email}\n"
                f"Date: {availability.date}\n"
                f"Time: {availability.start_time:%H:%M} – {availability.end_time:%H:%M}\n"
                f"Booking ID: #{booking.pk}"
            ),
            "start": {
                "dateTime": start_str,
                "timeZone": tz_str,
            },
            "end": {
                "dateTime": end_str,
                "timeZone": tz_str,
            },
            "attendees": [
                {"email": patient.email, "displayName": patient.get_full_name()},
                {"email": doctor.email,  "displayName": f"Dr. {doctor.get_full_name()}"},
            ],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},
                    {"method": "popup",  "minutes": 15},
                ],
            },
            "status": "confirmed",
        }

        results["patient_event_id"] = _create_event_for_user(
            patient_service, patient_calendar_id, patient_event_body
        )
    else:
        logger.warning("Skipping patient calendar event – no valid credentials for user %s.", patient.pk)

    return results if results else None


# ---------------------------------------------------------------------------
# OAuth2 Flow Helpers (call these from your OAuth callback view)
# ---------------------------------------------------------------------------

def get_google_auth_url(request) -> str:
    """
    Generate the Google OAuth2 authorisation URL to redirect users to.
    Use this in your /auth/google/ view.
    """
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id":     settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
            }
        },
        scopes=settings.GOOGLE_SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline",   # request refresh_token
        prompt="consent",        # force consent screen so refresh_token is always returned
        include_granted_scopes="true",
    )
    return auth_url


def handle_google_oauth_callback(request, user):
    """
    Exchange the authorisation code for access + refresh tokens and
    persist them on the User record.

    Call this inside your OAuth callback view, e.g.:
        GET /auth/google/callback/?code=<code>
    """
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id":     settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
            }
        },
        scopes=settings.GOOGLE_SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Exchange code for tokens
    flow.fetch_token(code=request.GET.get("code"))
    creds = flow.credentials

    # Persist tokens on the user record
    user.google_access_token  = creds.token
    user.google_refresh_token = creds.refresh_token
    user.google_token_expiry  = creds.expiry
    user.save(update_fields=[
        "google_access_token",
        "google_refresh_token",
        "google_token_expiry",
    ])
    logger.info("Stored Google OAuth tokens for user %s.", user.pk)
