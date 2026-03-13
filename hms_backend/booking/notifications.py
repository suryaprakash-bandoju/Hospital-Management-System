# notifications.py
# Mini Hospital Management System – Serverless Email Trigger
# ============================================================
# Django-side helper that POSTs a notification payload to the
# Serverless-Offline Lambda endpoint running at http://localhost:3000/
#
# Supported email_type values:
#   • SIGNUP_WELCOME
#   • BOOKING_CONFIRMATION
# ============================================================

import json
import logging
import urllib.request
import urllib.error

from django.conf import settings

logger = logging.getLogger(__name__)

# Base URL of the Serverless Offline emulator (override in settings if needed).
LAMBDA_BASE_URL = getattr(settings, "LAMBDA_BASE_URL", "http://localhost:3000")
SEND_EMAIL_PATH = "/send-email"           # matches the path in serverless.yml
LAMBDA_TIMEOUT  = 5                        # seconds – fire-and-forget; keep this short


def send_notification(
    email_type: str,
    recipient_email: str,
    details: dict,
) -> bool:
    """
    POST a notification request to the Serverless Lambda /send-email endpoint.

    Parameters
    ----------
    email_type      : str   – One of SIGNUP_WELCOME | BOOKING_CONFIRMATION
    recipient_email : str   – Destination email address
    details         : dict  – Arbitrary key/value pairs included in the email body

    Returns
    -------
    bool – True if the Lambda responded with HTTP 2xx, False otherwise.
           This is fire-and-forget: failures are logged but never raised.
    """
    payload = {
        "email_type":       email_type,
        "recipient_email":  recipient_email,
        "details":          details,
    }

    url          = f"{LAMBDA_BASE_URL}{SEND_EMAIL_PATH}"
    encoded_body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url     = url,
        data    = encoded_body,
        headers = {
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        method  = "POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LAMBDA_TIMEOUT) as response:
            status_code = response.status
            if 200 <= status_code < 300:
                logger.info(
                    "Lambda email sent | type=%s recipient=%s status=%s",
                    email_type, recipient_email, status_code,
                )
                return True
            else:
                logger.warning(
                    "Lambda returned non-2xx | type=%s recipient=%s status=%s",
                    email_type, recipient_email, status_code,
                )
                return False

    except urllib.error.URLError as exc:
        # Covers connection refused (Lambda not running), timeouts, DNS errors.
        logger.error(
            "Could not reach Lambda endpoint %s | type=%s recipient=%s error=%s",
            url, email_type, recipient_email, exc.reason,
        )
        return False

    except Exception as exc:
        logger.exception(
            "Unexpected error triggering Lambda | type=%s recipient=%s: %s",
            email_type, recipient_email, exc,
        )
        return False


# ---------------------------------------------------------------------------
# Usage examples (for documentation / tests – not executed at import time)
# ---------------------------------------------------------------------------
#
# 1. SIGNUP_WELCOME – called inside signup_view() after user creation:
#
#    send_notification(
#        email_type      = "SIGNUP_WELCOME",
#        recipient_email = user.email,
#        details         = {
#            "first_name": user.first_name,
#            "role":       "patient",
#        },
#    )
#
# 2. BOOKING_CONFIRMATION – called inside BookSlotView.post() after commit:
#
#    # To patient
#    send_notification(
#        email_type      = "BOOKING_CONFIRMATION",
#        recipient_email = patient.email,
#        details         = {
#            "recipient_role": "patient",
#            "doctor_name":    f"Dr. {doctor.get_full_name()}",
#            "patient_name":   patient.get_full_name(),
#            "date":           str(availability.date),
#            "start_time":     str(availability.start_time),
#            "end_time":       str(availability.end_time),
#            "booking_id":     booking.pk,
#        },
#    )
#
#    # To doctor
#    send_notification(
#        email_type      = "BOOKING_CONFIRMATION",
#        recipient_email = doctor.email,
#        details         = {
#            "recipient_role": "doctor",
#            ...same fields...
#        },
#    )
# ---------------------------------------------------------------------------
