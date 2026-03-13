# handler.py  (Serverless Framework Lambda)
# Mini Hospital Management System – Email Notification Microservice
# ============================================================
# Triggered by HTTP POST to /send-email
# Accepts JSON payload: { email_type, recipient_email, details }
# Sends email via Gmail SMTP using an App Password (smtplib).
#
# Environment variables required (set in serverless.yml / .env):
#   SMTP_HOST         – e.g. smtp.gmail.com
#   SMTP_PORT         – e.g. 587
#   SMTP_USER         – full Gmail address, e.g. noreply@yourhospital.com
#   SMTP_APP_PASSWORD – 16-char Gmail App Password (not your account password)
#   EMAIL_FROM_NAME   – Display name, e.g. "City Hospital"
# ============================================================

import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# SMTP configuration (from environment variables)
# ---------------------------------------------------------------------------

SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER         ="iamsurya788@gmail.com"
SMTP_APP_PASSWORD ="pzdbiiyeplsvfvrh"
EMAIL_FROM_NAME   = os.environ.get("EMAIL_FROM_NAME", "Hospital System")
FROM_ADDRESS      = f"{EMAIL_FROM_NAME} <{SMTP_USER}>"


# ---------------------------------------------------------------------------
# Email template builders
# ---------------------------------------------------------------------------

def _build_signup_welcome(details: dict) -> tuple[str, str, str]:
    """
    Returns (subject, plain_text_body, html_body) for SIGNUP_WELCOME emails.
    """
    first_name = details.get("first_name", "User")
    role       = details.get("role", "member").capitalize()

    subject = f"Welcome to City Hospital, {first_name}!"

    plain = (
        f"Hi {first_name},\n\n"
        f"Welcome aboard! Your account has been created as a {role}.\n\n"
        f"You can now log in and start using the Hospital Management System.\n\n"
        f"If you have any questions, please contact our support team.\n\n"
        f"Best regards,\n{EMAIL_FROM_NAME}"
    )

    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
      <h2 style="color:#2d6a9f;">Welcome to City Hospital, {first_name}! 🏥</h2>
      <p>Your account has been created successfully as a <strong>{role}</strong>.</p>
      <p>You can now log in to the Hospital Management System to:</p>
      <ul>
        {"<li>Browse available appointment slots</li><li>Manage your bookings</li>" if role == "Patient"
         else "<li>Manage your availability</li><li>View upcoming appointments</li>"}
      </ul>
      <p>If you have questions, reply to this email or contact support.</p>
      <br/>
      <p>Best regards,<br/><strong>{EMAIL_FROM_NAME}</strong></p>
    </body></html>
    """
    return subject, plain, html


def _build_booking_confirmation(details: dict) -> tuple[str, str, str]:
    """
    Returns (subject, plain_text_body, html_body) for BOOKING_CONFIRMATION emails.
    """
    recipient_role = details.get("recipient_role", "patient")
    doctor_name    = details.get("doctor_name", "the doctor")
    patient_name   = details.get("patient_name", "the patient")
    date_str       = details.get("date", "")
    start_time     = details.get("start_time", "")
    end_time       = details.get("end_time", "")
    booking_id     = details.get("booking_id", "N/A")

    if recipient_role == "doctor":
        subject        = f"New Appointment: {patient_name} on {date_str}"
        other_party    = f"Patient: {patient_name}"
        personal_note  = "Please ensure you are available at the scheduled time."
    else:
        subject        = f"Booking Confirmed: {doctor_name} on {date_str}"
        other_party    = f"Doctor: {doctor_name}"
        personal_note  = "Please arrive 10 minutes before your appointment."

    plain = (
        f"Booking Confirmation (#{booking_id})\n"
        f"{'─' * 40}\n"
        f"{other_party}\n"
        f"Date:  {date_str}\n"
        f"Time:  {start_time} – {end_time}\n"
        f"{'─' * 40}\n\n"
        f"{personal_note}\n\n"
        f"Best regards,\n{EMAIL_FROM_NAME}"
    )

    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
      <h2 style="color:#2d6a9f;">✅ Appointment Confirmed</h2>
      <p>Booking reference: <strong>#{booking_id}</strong></p>
      <table style="border-collapse:collapse; width:100%; max-width:480px;">
        <tr style="background:#f0f4f8;">
          <td style="padding:8px 12px; font-weight:bold;">{'Patient' if recipient_role == 'doctor' else 'Doctor'}</td>
          <td style="padding:8px 12px;">{patient_name if recipient_role == 'doctor' else doctor_name}</td>
        </tr>
        <tr>
          <td style="padding:8px 12px; font-weight:bold;">Date</td>
          <td style="padding:8px 12px;">{date_str}</td>
        </tr>
        <tr style="background:#f0f4f8;">
          <td style="padding:8px 12px; font-weight:bold;">Time</td>
          <td style="padding:8px 12px;">{start_time} – {end_time}</td>
        </tr>
      </table>
      <br/>
      <p><em>{personal_note}</em></p>
      <p>Best regards,<br/><strong>{EMAIL_FROM_NAME}</strong></p>
    </body></html>
    """
    return subject, plain, html


# ---------------------------------------------------------------------------
# Core SMTP sender
# ---------------------------------------------------------------------------

def _send_email(recipient_email: str, subject: str, plain_body: str, html_body: str) -> None:
    """
    Send a multi-part (plain + HTML) email via Gmail SMTP with STARTTLS.
    Raises smtplib.SMTPException on failure.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_ADDRESS
    msg["To"]      = recipient_email

    # Attach plain-text first; email clients show the last attached part
    # that they support, so HTML goes second (preferred).
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()          # Upgrade to TLS
        server.ehlo()
        server.login(SMTP_USER, SMTP_APP_PASSWORD)
        server.sendmail(SMTP_USER, recipient_email, msg.as_string())

    logger.info("Email sent to %s | subject='%s'", recipient_email, subject)


# ---------------------------------------------------------------------------
# Lambda Handler – Entry Point
# ---------------------------------------------------------------------------

def send_email(event, context):
    """
    AWS Lambda handler triggered by API Gateway HTTP POST /send-email.

    Expected JSON body:
    {
        "email_type":      "SIGNUP_WELCOME" | "BOOKING_CONFIRMATION",
        "recipient_email": "user@example.com",
        "details":         { ...template-specific key/value pairs... }
    }

    Returns an API Gateway-compatible response dict.
    """
    logger.info("Received event: %s", json.dumps(event))

    # ── Parse request body ────────────────────────────────────────────────
    try:
        # API Gateway wraps the body as a string.
        body = event.get("body") or "{}"
        if isinstance(body, str):
            body = json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Invalid JSON body: %s", exc)
        return _response(400, {"error": "Invalid JSON body."})

    email_type      = body.get("email_type", "").upper()
    recipient_email = body.get("recipient_email", "").strip()
    details         = body.get("details", {})

    # ── Validate required fields ──────────────────────────────────────────
    if not email_type or not recipient_email:
        return _response(400, {"error": "email_type and recipient_email are required."})

    supported_types = {"SIGNUP_WELCOME", "BOOKING_CONFIRMATION"}
    if email_type not in supported_types:
        return _response(
            400,
            {"error": f"Unknown email_type '{email_type}'. Supported: {sorted(supported_types)}"}
        )

    # ── Build email content ───────────────────────────────────────────────
    try:
        if email_type == "SIGNUP_WELCOME":
            subject, plain, html = _build_signup_welcome(details)
        elif email_type == "BOOKING_CONFIRMATION":
            subject, plain, html = _build_booking_confirmation(details)
    except Exception as exc:
        logger.exception("Error building email template: %s", exc)
        return _response(500, {"error": "Failed to build email content."})

    # ── Send via SMTP ─────────────────────────────────────────────────────
    try:
        _send_email(recipient_email, subject, plain, html)
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed – check SMTP_USER and SMTP_APP_PASSWORD.")
        return _response(500, {"error": "SMTP authentication failed."})
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", exc)
        return _response(500, {"error": f"Failed to send email: {exc}"})
    except Exception as exc:
        logger.exception("Unexpected error sending email: %s", exc)
        return _response(500, {"error": "An unexpected error occurred."})

    return _response(200, {
        "message":          "Email sent successfully.",
        "email_type":       email_type,
        "recipient_email":  recipient_email,
    })


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _response(status_code: int, body: dict) -> dict:
    """Helper to format an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",    # tighten in production
        },
        "body": json.dumps(body),
    }
