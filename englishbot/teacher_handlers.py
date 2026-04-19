from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .db import save_user
from .homework import (
    AssignmentGroupNotFoundError,
    EmptyAssignmentError,
    LearningItemNotFoundError,
    StudentLinkRequiredError,
    TeacherRoleRequiredError as HomeworkTeacherRoleRequiredError,
    create_assignment,
    create_assignment_from_group,
    list_assignable_groups,
)
from .homework_handlers import build_homework_button
from .runtime import router
from .teacher_student import (
    InviteAlreadyUsedError,
    InviteNotFoundError,
    StudentAlreadyLinkedError,
    TeacherRoleRequiredError,
    create_invite,
    join_with_invite,
)


def _build_assign_usage_message() -> str:
    groups = ", ".join(
        f"{group['name']} ({group['title']})"
        for group in list_assignable_groups()
    )
    return (
        "Использование: /assign <student_user_id> <group_name>\n"
        "Или: /assign <student_user_id> <learning_item_id,learning_item_id,...>\n"
        f"Доступные группы: {groups}"
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


@router.message(Command("assign"))
async def assign(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    raw_args = (command.args if command is not None and command.args is not None else "").strip()
    if not raw_args:
        await message.answer(_build_assign_usage_message())
        return

    parts = raw_args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(_build_assign_usage_message())
        return

    try:
        student_user_id = int(parts[0])
    except ValueError:
        await message.answer(_build_assign_usage_message())
        return

    assignment_target = parts[1].strip()
    raw_learning_item_ids = [
        item_id.strip()
        for item_id in assignment_target.split(",")
        if item_id.strip()
    ]

    try:
        if raw_learning_item_ids and all(item_id.isdigit() for item_id in raw_learning_item_ids):
            result = create_assignment(
                message.from_user.id,
                student_user_id,
                [int(item_id) for item_id in raw_learning_item_ids],
            )
        else:
            result = create_assignment_from_group(
                message.from_user.id,
                student_user_id,
                assignment_target,
            )
    except HomeworkTeacherRoleRequiredError:
        await message.answer("Команда /assign доступна только пользователю с ролью teacher.")
        return
    except StudentLinkRequiredError:
        await message.answer("Этот ученик не привязан к вашему teacher-профилю.")
        return
    except EmptyAssignmentError:
        await message.answer("Нужно передать хотя бы один learning_item_id.")
        return
    except LearningItemNotFoundError:
        await message.answer("Один из learning_item_id не найден.")
        return
    except AssignmentGroupNotFoundError:
        await message.answer(_build_assign_usage_message())
        return

    await message.answer(
        f"Задание создано. assignment_id: {result['assignment_id']}. "
        f"Название: {result['title']}"
    )
    await message.bot.send_message(
        chat_id=int(result["notification"]["student_user_id"]),
        text=str(result["notification"]["text"]),
        reply_markup=build_homework_button(),
    )
