from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .db import save_user
from .runtime import router
from .teacher_student import (
    InviteAlreadyUsedError,
    InviteNotFoundError,
    StudentAlreadyLinkedError,
    TeacherRoleRequiredError,
    create_invite,
    join_with_invite,
)


@router.message(Command("invite"))
async def invite(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    try:
        code = create_invite(message.from_user.id)
    except TeacherRoleRequiredError:
        await message.answer("Команда /invite доступна только пользователю с ролью teacher.")
        return

    await message.answer(f"Код приглашения: {code}")


@router.message(Command("join"))
async def join(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    code = (command.args if command is not None and command.args is not None else "").strip()
    if not code:
        await message.answer("Использование: /join <code>")
        return

    try:
        teacher_user_id = join_with_invite(message.from_user.id, code)
    except InviteNotFoundError:
        await message.answer("Приглашение не найдено.")
        return
    except InviteAlreadyUsedError:
        await message.answer("Это приглашение уже использовано.")
        return
    except StudentAlreadyLinkedError:
        await message.answer("Ученик уже привязан к учителю.")
        return

    await message.answer(f"Присоединение выполнено. teacher_user_id: {teacher_user_id}")
