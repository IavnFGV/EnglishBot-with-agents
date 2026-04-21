from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .command_registry import CANCEL_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .training import cancel_active_training_session


@router.message(Command(CANCEL_COMMAND.name))
async def cancel_current_flow(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    had_state = await state.get_state() is not None or bool(await state.get_data())
    had_training = cancel_active_training_session(message.from_user.id)
    await state.clear()

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "flow.cancelled" if had_state or had_training else "flow.nothing_to_cancel",
        )
    )
