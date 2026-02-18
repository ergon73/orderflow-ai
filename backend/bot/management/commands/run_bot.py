import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from django.core.management.base import BaseCommand, CommandError

from bot.handlers import router


async def _start_polling(token: str) -> None:
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


class Command(BaseCommand):
    help = "Run Telegram bot via aiogram polling."

    def handle(self, *args, **options):
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set")

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.stdout.write(self.style.SUCCESS("Starting Telegram bot polling..."))
        asyncio.run(_start_polling(token))
