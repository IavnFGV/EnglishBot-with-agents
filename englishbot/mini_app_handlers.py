"""Telegram choice between the two learner training interfaces."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram_dialog import DialogManager

from .build_info import load_build_info
from .config import get_mini_app_url
from .i18n import translate_for_user
from .learner_training_dialog import start_training_dialog
from .runtime import router
from .training import get_active_training_session
from .training_handlers import render_started_training_session


CHOOSE_TELEGRAM_PREFIX = "mini:telegram:"


def build_mini_app_url(base_url: str, session_id: int) -> str:
    parsed = urlsplit(base_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key not in {"session", "v"}]
    query.append(("session", str(session_id)))
    commit = load_build_info().git_commit
    if commit != "unknown":
        query.append(("v", commit[:12]))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


async def offer_training_interfaces(message: Message, user_id: int) -> bool:
    base_url = get_mini_app_url()
    if base_url is None or getattr(getattr(message, "chat", None), "type", "private") != "private":
        return False
    session = get_active_training_session(user_id)
    if session is None:
        return False
    session_id = int(session["id"])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=translate_for_user(user_id, "mini_app.open"), web_app=WebAppInfo(url=build_mini_app_url(base_url, session_id)))],
        [InlineKeyboardButton(text=translate_for_user(user_id, "mini_app.telegram"), callback_data=f"{CHOOSE_TELEGRAM_PREFIX}{session_id}")],
    ])
    await message.answer(translate_for_user(user_id, "mini_app.choose"), reply_markup=keyboard)
    return True


@router.callback_query(lambda callback: callback.data is not None and callback.data.startswith(CHOOSE_TELEGRAM_PREFIX))
async def choose_telegram_training(callback: CallbackQuery, dialog_manager: DialogManager | None = None) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None or callback.data is None:
        return
    session = get_active_training_session(callback.from_user.id)
    if session is None or callback.data != f"{CHOOSE_TELEGRAM_PREFIX}{session['id']}":
        await callback.message.answer(translate_for_user(callback.from_user.id, "mini_app.stale_choice"))
        return
    if dialog_manager is None:
        await render_started_training_session(callback.message, callback.from_user.id)
    else:
        await start_training_dialog(callback.message, dialog_manager, callback.from_user.id)
