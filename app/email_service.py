import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

logger = logging.getLogger(__name__)


def send_inquiry_email(name, phone, email, company, equipment, message):
    smtp_server = current_app.config.get("MAIL_SERVER", "")
    smtp_port = current_app.config.get("MAIL_PORT", 587)
    smtp_use_tls = current_app.config.get("MAIL_USE_TLS", True)
    smtp_username = current_app.config.get("MAIL_USERNAME", "")
    smtp_password = current_app.config.get("MAIL_PASSWORD", "")
    smtp_from = current_app.config.get("MAIL_DEFAULT_SENDER", smtp_username)
    admin_to = current_app.config.get("MAIL_RECIPIENT", smtp_username)

    if not smtp_server or not smtp_username or not smtp_password:
        logger.warning("Email not sent: SMTP not configured")
        return False

    subject = f"New Quote Request from {name}"
    body = f"""
New Contact / Quote Request
============================

Name:       {name}
Phone:      {phone}
Email:      {email or 'N/A'}
Company:    {company or 'N/A'}
Equipment:  {equipment or 'N/A'}

Message:
{message}

---
This email was sent from the Current Link website contact form.
"""

    msg = MIMEMultipart()
    msg["From"] = smtp_from
    msg["To"] = admin_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        if smtp_use_tls:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_from, [admin_to], msg.as_string())
        server.quit()
        logger.info(f"Inquiry email sent successfully for {name}")
        return True
    except Exception as e:
        logger.error(f"Failed to send inquiry email: {e}")
        return False
