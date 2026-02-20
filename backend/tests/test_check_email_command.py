from email.message import EmailMessage
from unittest.mock import MagicMock
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from orders.models import Customer, IntakeMessage


class CheckEmailCommandTests(TestCase):
    def test_command_requires_imap_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("check_email")

    @patch.dict(
        "os.environ",
        {
            "EMAIL_IMAP_HOST": "imap.example.com",
            "EMAIL_IMAP_PORT": "993",
            "EMAIL_LOGIN": "orders@example.com",
            "EMAIL_PASSWORD": "pwd",
            "EMAIL_IMAP_MAILBOX": "INBOX",
        },
        clear=False,
    )
    @patch("orders.management.commands.check_email.process_intake_message")
    @patch("orders.management.commands.check_email.create_email_intake")
    @patch("orders.management.commands.check_email.get_or_create_email_customer")
    @patch("orders.management.commands.check_email.imaplib.IMAP4_SSL")
    def test_command_processes_unseen_email(
        self,
        imap_cls,
        get_customer,
        create_intake,
        process_intake,
    ):
        customer = Customer.objects.create(name="Email User", email="user@example.com")
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.EMAIL,
            raw_text="placeholder",
            customer=customer,
            idempotency_key="email_test_1",
        )
        get_customer.return_value = customer
        create_intake.return_value = (intake, True)

        msg = EmailMessage()
        msg["From"] = "User <user@example.com>"
        msg["Subject"] = "Новый заказ"
        msg.set_content("Хочу кружку 2 шт на Ленина 10")

        mail = MagicMock()
        mail.login.return_value = ("OK", [b"logged"])
        mail.select.return_value = ("OK", [b""])
        mail.status.return_value = ("OK", [b"INBOX (UIDVALIDITY 12345)"])

        def _uid_side_effect(command, *_args):
            if command == "search":
                return ("OK", [b"77"])
            if command == "fetch":
                return ("OK", [(b"1 (RFC822 {1})", msg.as_bytes())])
            return ("NO", [])

        mail.uid.side_effect = _uid_side_effect
        imap_cls.return_value = mail

        call_command("check_email")

        process_intake.assert_called_once_with(intake=intake)

    @patch.dict(
        "os.environ",
        {
            "EMAIL_IMAP_HOST": "imap.example.com",
            "EMAIL_IMAP_PORT": "993",
            "EMAIL_LOGIN": "orders@example.com",
            "EMAIL_PASSWORD": "pwd",
            "EMAIL_IMAP_MAILBOX": "INBOX",
        },
        clear=False,
    )
    @patch("orders.management.commands.check_email.process_intake_message")
    @patch("orders.management.commands.check_email.create_email_intake")
    @patch("orders.management.commands.check_email.get_or_create_email_customer")
    @patch("orders.management.commands.check_email.imaplib.IMAP4_SSL")
    def test_command_skips_duplicate_email_intake(
        self,
        imap_cls,
        get_customer,
        create_intake,
        process_intake,
    ):
        customer = Customer.objects.create(name="Email User", email="user@example.com")
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.EMAIL,
            raw_text="placeholder",
            customer=customer,
            idempotency_key="email_test_2",
        )
        get_customer.return_value = customer
        create_intake.return_value = (intake, False)

        msg = EmailMessage()
        msg["From"] = "User <user@example.com>"
        msg["Subject"] = "Duplicate"
        msg.set_content("дубль")

        mail = MagicMock()
        mail.login.return_value = ("OK", [b"logged"])
        mail.select.return_value = ("OK", [b""])
        mail.status.return_value = ("OK", [b"INBOX (UIDVALIDITY 12345)"])

        def _uid_side_effect(command, *_args):
            if command == "search":
                return ("OK", [b"88"])
            if command == "fetch":
                return ("OK", [(b"1 (RFC822 {1})", msg.as_bytes())])
            return ("NO", [])

        mail.uid.side_effect = _uid_side_effect
        imap_cls.return_value = mail

        call_command("check_email")

        process_intake.assert_not_called()
