"""SMTP transport, restricted local capture mode, and content-safe templates."""

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings
from app.schemas.email_address import validate_address


def send_case_email(row):
    settings = get_settings()
    validate_address(row.recipient)
    validate_address(settings.email_from)
    if settings.email_delivery_mode == "local":
        if settings.smtp_host not in {"localhost", "127.0.0.1", "mailpit"}:
            raise ValueError("Local capture requires a local SMTP host")
    elif not settings.smtp_starttls:
        raise ValueError("External SMTP requires STARTTLS")
    states = {
        "case_approved": "approved; simulated refund execution is still pending",
        "case_rejected": "rejected; contact support if you want reconsideration",
        "case_resolved": "resolved through a simulation. No money was moved",
    }
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = row.recipient
    message["Subject"] = (
        "Verify your SupportFlow email"
        if row.kind == "verify_account"
        else "SupportFlow case status update"
    )
    message["Message-ID"] = f"<{row.id}@supportflow.local>"
    if row.kind == "verify_account":
        message.set_content(
            f"Your SupportFlow verification code is {row.verification_code}.\n"
            "It expires in 15 minutes. Enter it on the verification page.\n"
            "If you did not request an account, ignore this email.\n"
        )
    else:
        message.set_content(
            f"Your case {row.case_id} is {states[row.kind]}.\n\n"
            "Ask for the case status in SupportFlow for details.\n"
            "You can turn off email updates in your case subscription settings.\n"
        )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.email_delivery_mode == "smtp":
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
