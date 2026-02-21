from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from django.core.management.base import BaseCommand, CommandError

from ai_parser.services import process_intake_message
from orders.services import create_email_intake, get_or_create_email_customer

logger = logging.getLogger(__name__)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_text_body(message: email.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = part.get("Content-Disposition", "")
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="ignore").strip()
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="ignore").strip()


def _uidvalidity_from_status(response: bytes | str) -> str:
    text = response.decode() if isinstance(response, bytes) else str(response)
    match = re.search(r"UIDVALIDITY\s+(\d+)", text)
    return match.group(1) if match else "0"


class Command(BaseCommand):
    help = "Read unseen IMAP emails and create IntakeMessage entries."

    def handle(self, *args, **options):
        host = os.getenv("EMAIL_IMAP_HOST")
        port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
        username = os.getenv("EMAIL_LOGIN")
        password = os.getenv("EMAIL_PASSWORD")
        mailbox = os.getenv("EMAIL_IMAP_MAILBOX", "INBOX")

        if not host or not username or not password:
            raise CommandError(
                "EMAIL_IMAP_HOST, EMAIL_LOGIN and EMAIL_PASSWORD must be configured"
            )

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

        self.stdout.write(f"Checking mailbox {mailbox} on {host}:{port}...")

        mail = imaplib.IMAP4_SSL(host, port)
        try:
            mail.login(username, password)
            status, _ = mail.select(mailbox)
            if status != "OK":
                raise CommandError(f"Cannot select mailbox {mailbox}")

            status_resp, status_data = mail.status(mailbox, "(UIDVALIDITY)")
            if status_resp != "OK":
                uidvalidity = "0"
            else:
                uidvalidity = _uidvalidity_from_status(status_data[0])

            typ, data = mail.uid("search", None, "UNSEEN")
            if typ != "OK":
                raise CommandError("Cannot search unseen emails")

            uids = data[0].split() if data and data[0] else []
            if not uids:
                self.stdout.write(self.style.WARNING("No unseen emails found."))
                return

            processed = 0
            for uid_bytes in uids:
                uid = uid_bytes.decode()
                typ, msg_data = mail.uid("fetch", uid, "(RFC822)")
                if typ != "OK" or not msg_data:
                    logger.warning("cannot fetch uid=%s", uid)
                    continue

                raw_email = msg_data[0][1]
                message = email.message_from_bytes(raw_email)
                sender_name, sender_email = parseaddr(message.get("From", ""))
                subject = _decode_header(message.get("Subject", ""))
                body = _extract_text_body(message)
                full_text = f"{subject}\n\n{body}".strip()

                customer = get_or_create_email_customer(
                    from_email=sender_email,
                    display_name=sender_name,
                )
                intake, created = create_email_intake(
                    customer=customer,
                    text=full_text,
                    mailbox=mailbox,
                    uidvalidity=uidvalidity,
                    uid=uid,
                    metadata={
                        "subject": subject,
                        "from_email": sender_email,
                    },
                )
                if not created:
                    logger.info("duplicate email intake skipped uid=%s", uid)
                    continue

                process_intake_message(intake=intake)
                processed += 1

            self.stdout.write(self.style.SUCCESS(f"Processed emails: {processed}"))
        finally:
            try:
                mail.close()
            except Exception as exc:
                logger.debug("mail.close failed: %s", exc)
            try:
                mail.logout()
            except Exception as exc:
                logger.debug("mail.logout failed: %s", exc)
