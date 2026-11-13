"""예전 자리. 텔레그램 구현은 jhq.messengers.telegram 으로 옮겼다(메신저 층)."""

from .messengers.telegram import (API, FILE_API, LIMIT, MAX_FILE, WORK_MARK, Bot, Messenger, TelegramMessenger,  # noqa: F401
                                  TgError, plain_text, split, to_html)
