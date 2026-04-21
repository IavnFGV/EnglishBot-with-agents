from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .command_registry import (
    ASSIGN_COMMAND,
    GRANTTOPIC_COMMAND,
    INVITE_COMMAND,
    JOIN_COMMAND,
)
from .db import save_user
from .homework import (
    AssignmentGroupNotFoundError,
    EmptyAssignmentError,
    LearningItemNotFoundError,
    MixedWorkspaceAssignmentError,
    StudentWorkspaceMembershipRequiredError,
    TeacherWorkspaceMembershipRequiredError,
    TeacherRoleRequiredError as HomeworkTeacherRoleRequiredError,
    create_assignment,
    create_assignment_from_group,
)
from .homework_handlers import build_homework_button
from .i18n import translate_for_user
from .runtime import router
from .teacher_student import (
    InviteAlreadyUsedError,
    InviteNotFoundError,
    StudentAlreadyLinkedError,
    TeacherRoleRequiredError,
    create_invite,
    join_with_invite,
)
from .user_profiles import get_user_role
from .topic_access import (
    StudentWorkspaceMembershipRequiredError as TopicAccessStudentWorkspaceMembershipRequiredError,
    TeacherWorkspaceMembershipRequiredError as TopicAccessTeacherWorkspaceMembershipRequiredError,
    TeacherRoleRequiredError as TopicAccessTeacherRoleRequiredError,
    TopicNotFoundError,
    grant_topic_access,
)

def _build_assign_usage_message(telegram_user_id: int) -> str:
    return translate_for_user(
        telegram_user_id,
        "teacher.assign.usage",
        command=ASSIGN_COMMAND.token,
    )


def _build_grant_topic_usage_message(telegram_user_id: int) -> str:
    return translate_for_user(
        telegram_user_id,
        "teacher.granttopic.usage",
        command=GRANTTOPIC_COMMAND.token,
    )


@router.message(Command(INVITE_COMMAND.name))
async def invite(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    try:
        code = create_invite(message.from_user.id)
    except TeacherRoleRequiredError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=INVITE_COMMAND.token,
            )
        )
        return

    await message.answer(
        translate_for_user(message.from_user.id, "teacher.invite.code", code=code)
    )


@router.message(Command(JOIN_COMMAND.name))
async def join(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    code = (command.args if command is not None and command.args is not None else "").strip()
    if not code:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.join.usage",
                command=JOIN_COMMAND.token,
            )
        )
        return

    try:
        teacher_user_id = join_with_invite(message.from_user.id, code)
    except InviteNotFoundError:
        await message.answer(translate_for_user(message.from_user.id, "teacher.join.not_found"))
        return
    except InviteAlreadyUsedError:
        await message.answer(translate_for_user(message.from_user.id, "teacher.join.used"))
        return
    except StudentAlreadyLinkedError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.join.already_linked")
        )
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "teacher.join.success",
            teacher_user_id=teacher_user_id,
        )
    )


@router.message(Command(ASSIGN_COMMAND.name))
async def assign(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    raw_args = (command.args if command is not None and command.args is not None else "").strip()
    if not raw_args:
        await message.answer(_build_assign_usage_message(message.from_user.id))
        return

    parts = raw_args.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(_build_assign_usage_message(message.from_user.id))
        return

    try:
        student_user_id = int(parts[0])
    except ValueError:
        await message.answer(_build_assign_usage_message(message.from_user.id))
        return

    try:
        if len(parts) == 2:
            assignment_target = parts[1].strip()
            raw_learning_item_ids = [
                item_id.strip()
                for item_id in assignment_target.split(",")
                if item_id.strip()
            ]
            if not raw_learning_item_ids or not all(
                item_id.isdigit() for item_id in raw_learning_item_ids
            ):
                await message.answer(_build_assign_usage_message(message.from_user.id))
                return
            result = create_assignment(
                message.from_user.id,
                student_user_id,
                [int(item_id) for item_id in raw_learning_item_ids],
            )
        else:
            teacher_workspace_id = int(parts[1])
            assignment_target = parts[2].strip()
            if not assignment_target:
                await message.answer(_build_assign_usage_message(message.from_user.id))
                return
            result = create_assignment_from_group(
                message.from_user.id,
                student_user_id,
                teacher_workspace_id,
                assignment_target,
            )
    except ValueError:
        await message.answer(_build_assign_usage_message(message.from_user.id))
        return
    except HomeworkTeacherRoleRequiredError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=ASSIGN_COMMAND.token,
            )
        )
        return
    except TeacherWorkspaceMembershipRequiredError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.assign.no_source_access")
        )
        return
    except StudentWorkspaceMembershipRequiredError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.assign.no_shared_workspace")
        )
        return
    except EmptyAssignmentError:
        await message.answer(translate_for_user(message.from_user.id, "teacher.assign.empty"))
        return
    except LearningItemNotFoundError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.assign.item_not_found")
        )
        return
    except MixedWorkspaceAssignmentError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.assign.mixed_workspaces")
        )
        return
    except AssignmentGroupNotFoundError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.assign.topic_not_found")
        )
        return

    assignment_title = (
        str(result["title"])
        if result.get("title")
        else translate_for_user(message.from_user.id, "homework.default_title")
    )
    await message.answer(
        translate_for_user(
            message.from_user.id,
            "teacher.assign.success",
            assignment_id=result["assignment_id"],
            title=assignment_title,
        )
    )
    await message.bot.send_message(
        chat_id=int(result["student_user_id"]),
        text=translate_for_user(
            int(result["student_user_id"]),
            "homework.notification.assigned",
            title=translate_for_user(
                int(result["student_user_id"]),
                "homework.default_title",
            )
            if not result.get("title")
            else result["title"],
        ),
        reply_markup=build_homework_button(int(result["student_user_id"])),
    )


@router.message(Command(GRANTTOPIC_COMMAND.name))
async def grant_topic(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    raw_args = (command.args if command is not None and command.args is not None else "").strip()
    if not raw_args:
        await message.answer(_build_grant_topic_usage_message(message.from_user.id))
        return

    parts = raw_args.split(maxsplit=2)
    if len(parts) != 3:
        await message.answer(_build_grant_topic_usage_message(message.from_user.id))
        return

    try:
        student_user_id = int(parts[0])
        teacher_workspace_id = int(parts[1])
    except ValueError:
        await message.answer(_build_grant_topic_usage_message(message.from_user.id))
        return

    try:
        result = grant_topic_access(
            message.from_user.id,
            student_user_id,
            teacher_workspace_id,
            parts[2],
        )
    except TopicAccessTeacherRoleRequiredError:
        await message.answer(
            translate_for_user(
                message.from_user.id,
                "teacher.command_teacher_only",
                command=GRANTTOPIC_COMMAND.token,
            )
        )
        return
    except TopicAccessTeacherWorkspaceMembershipRequiredError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.granttopic.no_source_access")
        )
        return
    except TopicAccessStudentWorkspaceMembershipRequiredError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.granttopic.no_shared_workspace")
        )
        return
    except TopicNotFoundError:
        await message.answer(
            translate_for_user(message.from_user.id, "teacher.granttopic.topic_not_found")
        )
        return

    await message.answer(
        translate_for_user(
            message.from_user.id,
            "teacher.granttopic.success",
            topic_title=result["topic_title"],
            topic_name=result["topic_name"],
        )
    )
