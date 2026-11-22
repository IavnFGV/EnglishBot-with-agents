from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram_dialog import DialogManager, StartMode

from .command_registry import TEACHER_CONTENT_COMMAND
from .config import get_mini_app_url
from .db import save_user
from .families import get_user_family
from .i18n import translate_for_user
from .runtime import router
from .teacher_content_dialog import TeacherContentDialogSG


TELEGRAM_EDITOR_CALLBACK = "editor:telegram"


def build_editor_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/editor"


def build_editor_keyboard(user_id: int, base_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=translate_for_user(user_id, "editor.open_button"),
            web_app=WebAppInfo(url=build_editor_url(base_url)),
        )],
        [InlineKeyboardButton(
            text=translate_for_user(user_id, "editor.telegram_editor"),
            callback_data=TELEGRAM_EDITOR_CALLBACK,
        )],
    ])


async def _start_telegram_editor(dialog_manager: DialogManager, family_id: int) -> None:
    await dialog_manager.start(
        TeacherContentDialogSG.topics,
        mode=StartMode.RESET_STACK,
        data={"family_id": family_id},
    )


@router.message(Command(TEACHER_CONTENT_COMMAND.name))
async def teacher_content(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    family = get_user_family(message.from_user.id)
    if family is None:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.command_family_only",
                command=TEACHER_CONTENT_COMMAND.token,
            )
        )
        return

    base_url = get_mini_app_url()
    if base_url is not None and getattr(message.chat, "type", "private") == "private":
        await message.answer(
            translate_for_user(message.from_user.id, "editor.intro"),
            reply_markup=build_editor_keyboard(message.from_user.id, base_url),
        )
        return

    await _start_telegram_editor(dialog_manager, int(family["id"]))


@router.callback_query(lambda callback: callback.data == TELEGRAM_EDITOR_CALLBACK)
async def open_telegram_editor(callback: CallbackQuery, dialog_manager: DialogManager) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    family = get_user_family(callback.from_user.id)
    if family is None:
        return
    await _start_telegram_editor(dialog_manager, int(family["id"]))
