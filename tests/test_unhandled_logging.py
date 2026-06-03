import asyncio
from datetime import datetime
import pytest
from unittest.mock import patch
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, User, Update, CallbackQuery, ErrorEvent, Chat
from aiogram_dialog.api.exceptions import UnknownIntent

# We import the handlers directly to test them in isolation
from englishbot.bot import unhandled_message, on_error

def test_unhandled_message_logs_warning():
    """
    Verifies that any message reaching the unhandled_router 
    triggers a warning log with the user ID and text.
    """
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=123, type="private")
    # Mock message with text
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="/unknown_command")
    
    with patch("englishbot.bot.logger") as mock_logger:
        asyncio.run(unhandled_message(message))
        mock_logger.warning.assert_called_once_with(
            "Unhandled message or command from user %s: %s", 123, "/unknown_command"
        )

def test_on_error_unknown_intent_logs_warning():
    """
    Verifies that the UnknownIntent exception is caught and logged as a warning.
    """
    user = User(id=456, is_bot=False, first_name="Test")
    callback_query = CallbackQuery(id="1", from_user=user, chat_instance="1")
    update = Update(update_id=1, callback_query=callback_query)
    event = ErrorEvent(update=update, exception=UnknownIntent())
    
    with patch("englishbot.bot.logger") as mock_logger:
        asyncio.run(on_error(event))
        mock_logger.warning.assert_called_once_with(
            "Unknown dialog intent detected for user %s", 456
        )


def test_on_error_ignores_message_not_modified_globally():
    update = Update(update_id=2)
    event = ErrorEvent(
        update=update,
        exception=TelegramBadRequest(
            method="editMessageText",
            message="Telegram server says - Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message",
        ),
    )

    with patch("englishbot.bot.logger") as mock_logger:
        asyncio.run(on_error(event))
        mock_logger.debug.assert_called_once()
        mock_logger.exception.assert_not_called()


def test_on_error_keeps_other_telegram_bad_requests_as_errors():
    update = Update(update_id=3)
    event = ErrorEvent(
        update=update,
        exception=TelegramBadRequest(
            method="editMessageText",
            message="Telegram server says - Bad Request: message to edit not found",
        ),
    )

    with patch("englishbot.bot.logger") as mock_logger:
        asyncio.run(on_error(event))
        mock_logger.exception.assert_called_once()
