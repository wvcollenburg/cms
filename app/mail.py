"""Plain SMTP: Mailpit locally, the STRATO mailbox or an EU provider in production."""
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from flask import current_app, render_template
from flask_babel import force_locale

# Tests read this instead of SMTP when MAIL_SUPPRESS is on.
outbox: list[EmailMessage] = []


def send_mail(to: str, subject: str, body: str) -> None:
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    if cfg.get("MAIL_SUPPRESS"):
        outbox.append(msg)
        return
    with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=10) as smtp:
        if cfg["MAIL_USE_TLS"]:
            smtp.starttls()
        if cfg["MAIL_USERNAME"]:
            smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        smtp.send_message(msg)


def send_template(user, template: str, subject_fn, **ctx) -> None:
    """Render mail/<template>.txt in the recipient's own ui_lang (§7)."""
    with force_locale(user.ui_lang):
        subject = str(subject_fn())
        body = render_template(f"mail/{template}.txt", user=user, **ctx)
    send_mail(user.email, subject, body)
