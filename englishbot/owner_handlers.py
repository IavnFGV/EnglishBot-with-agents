from aiogram.filters import Command
from aiogram.types import Message

from .command_registry import ADD_FAMILY_COMMAND
from .config import get_owner_telegram_user_id
from .db import get_user, save_user
from .families import FamilyMembershipError, add_user_to_owner_family
from .i18n import translate_for_user
from .runtime import router


@router.message(Command(ADD_FAMILY_COMMAND.name))
async def add_family(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return

    save_user(message.from_user)
    owner_user_id = get_owner_telegram_user_id()
    if owner_user_id is None or message.from_user.id != owner_user_id:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "owner.command_owner_only",
                command=ADD_FAMILY_COMMAND.token,
            )
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.add.usage",
                command=ADD_FAMILY_COMMAND.token,
            )
        )
        return

    try:
        target_user_id = int(parts[1].strip())
    except ValueError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.add.usage",
                command=ADD_FAMILY_COMMAND.token,
            )
        )
        return

    if get_user(target_user_id) is None:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.add.target_missing",
                telegram_user_id=target_user_id,
            )
        )
        return

    try:
        family, status = add_user_to_owner_family(message.from_user.id, target_user_id)
    except FamilyMembershipError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "family.add.conflict",
                telegram_user_id=target_user_id,
            )
        )
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            f"family.add.{status}",
            family_name=str(family["name"] or "Home"),
            telegram_user_id=target_user_id,
        )
    )
