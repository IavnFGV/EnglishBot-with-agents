from json import dumps
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.methods.base import TelegramMethod
from aiogram.types import Update

from .db import save_interaction


def serialize_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return dumps(value, ensure_ascii=False, default=str)


def extract_incoming_interaction(update: Update) -> tuple[int | None, str, str]:
    if update.message is not None and update.message.from_user is not None:
        text = update.message.text or update.message.caption or ""
        interaction_type = "command" if text.startswith("/") else "text"
        return update.message.from_user.id, interaction_type, text

    if update.callback_query is not None and update.callback_query.from_user is not None:
        return (
            update.callback_query.from_user.id,
            "callback",
            update.callback_query.data or "",
        )

    payload = update.model_dump(exclude_none=True, warnings=False)
    for field_name in (
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "inline_query",
        "chosen_inline_result",
        "shipping_query",
        "pre_checkout_query",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
    ):
        event = getattr(update, field_name, None)
        from_user = getattr(event, "from_user", None) if event is not None else None
        if from_user is not None:
            return from_user.id, field_name, serialize_content(payload)

    return None, "update", serialize_content(payload)


def extract_outgoing_interaction(method: TelegramMethod[Any]) -> tuple[int | None, str, str]:
    payload = method.model_dump(exclude_none=True, warnings=False)
    telegram_user_id = payload.get("chat_id")
    if not isinstance(telegram_user_id, int):
        telegram_user_id = None

    if "text" in payload and isinstance(payload["text"], str):
        content = payload["text"]
    elif "caption" in payload and isinstance(payload["caption"], str):
        content = payload["caption"]
    else:
        content = serialize_content(payload)

    return telegram_user_id, method.__api_method__, content


class InteractionLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        telegram_user_id, interaction_type, content = extract_incoming_interaction(event)
        if telegram_user_id is not None:
            save_interaction(telegram_user_id, "in", interaction_type, content)
        return await handler(event, data)


class OutgoingLoggingMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod[Any]], Awaitable[Any]],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        result = await make_request(bot, method)
        telegram_user_id, interaction_type, content = extract_outgoing_interaction(method)
        if telegram_user_id is not None:
            save_interaction(telegram_user_id, "out", interaction_type, content)
        return result
