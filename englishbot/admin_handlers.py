from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .admin_access import (
    AdminAccessDeniedError,
    RegisteredUserNotFoundError,
    add_user_to_student_workspace,
    ensure_admin_access,
    ensure_default_spaces_for_user,
    ensure_shared_family_workspace,
    get_registered_user_for_admin,
    grant_teacher_role,
    keep_student_role,
    list_registered_users_for_admin,
)
from .command_registry import ADMIN_COMMAND
from .db import save_user
from .i18n import translate_for_user
from .runtime import router
from .workspaces import ROLE_STUDENT, ROLE_TEACHER


ADMIN_USERS_PAGE_SIZE = 6
ADMIN_CALLBACK_PREFIX = "admin"


def _build_users_keyboard(
    telegram_user_id: int,
    users: list[dict[str, object]],
    page: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    start = max(page, 0) * ADMIN_USERS_PAGE_SIZE
    end = start + ADMIN_USERS_PAGE_SIZE
    for user in users[start:end]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(user["display_name"]),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:user:{int(user['telegram_user_id'])}:{max(page, 0)}"
                    ),
                )
            ]
        )

    navigation_buttons: list[InlineKeyboardButton] = []
    if start > 0:
        navigation_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(telegram_user_id, "admin.action.prev"),
                callback_data=f"{ADMIN_CALLBACK_PREFIX}:page:{page - 1}",
            )
        )
    if end < len(users):
        navigation_buttons.append(
            InlineKeyboardButton(
                text=translate_for_user(telegram_user_id, "admin.action.next"),
                callback_data=f"{ADMIN_CALLBACK_PREFIX}:page:{page + 1}",
            )
        )
    if navigation_buttons:
        rows.append(navigation_buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_user_detail_keyboard(
    actor_user_id: int,
    telegram_user_id: int,
    page: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate_for_user(actor_user_id, "admin.action.make_teacher"),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:act:{telegram_user_id}:make_teacher:{page}"
                    ),
                ),
                InlineKeyboardButton(
                    text=translate_for_user(actor_user_id, "admin.action.keep_student"),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:act:{telegram_user_id}:keep_student:{page}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        actor_user_id,
                        "admin.action.create_default_spaces",
                    ),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:act:{telegram_user_id}:create_default_spaces:{page}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        actor_user_id,
                        "admin.action.link_family_teacher",
                    ),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:act:{telegram_user_id}:link_family_teacher:{page}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text=translate_for_user(
                        actor_user_id,
                        "admin.action.link_family_student",
                    ),
                    callback_data=(
                        f"{ADMIN_CALLBACK_PREFIX}:act:{telegram_user_id}:link_family_student:{page}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text=translate_for_user(actor_user_id, "admin.action.back"),
                    callback_data=f"{ADMIN_CALLBACK_PREFIX}:page:{page}",
                )
            ],
        ]
    )


def _render_users_screen(telegram_user_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    users = list_registered_users_for_admin(telegram_user_id)
    start = max(page, 0) * ADMIN_USERS_PAGE_SIZE
    end = min(start + ADMIN_USERS_PAGE_SIZE, len(users))
    if not users:
        return (
            translate_for_user(telegram_user_id, "admin.screen.users.empty"),
            InlineKeyboardMarkup(inline_keyboard=[]),
        )

    lines = []
    for index, user in enumerate(users[start:end], start=start + 1):
        lines.append(
            translate_for_user(
                telegram_user_id,
                "admin.screen.users.line",
                index=index,
                display_name=user["display_name"],
                telegram_user_id=user["telegram_user_id"],
                role=translate_for_user(
                    telegram_user_id,
                    f"admin.role.{user['role']}",
                ),
            )
        )
    return (
        translate_for_user(
            telegram_user_id,
            "admin.screen.users.title",
            range_start=start + 1,
            range_end=end,
            total_count=len(users),
            user_lines="\n".join(lines),
        ),
        _build_users_keyboard(telegram_user_id, users, page),
    )


def _render_user_screen(
    telegram_user_id: int,
    target_user_id: int,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    user = get_registered_user_for_admin(telegram_user_id, target_user_id)
    workspace_lines = [
        translate_for_user(
            telegram_user_id,
            "admin.screen.user.workspace_line",
            workspace_id=workspace["id"],
            workspace_name=workspace["name"] or translate_for_user(
                telegram_user_id,
                "admin.workspace.unnamed",
            ),
            workspace_kind=workspace["kind"],
            membership_role=workspace["role"],
        )
        for workspace in user["workspaces"]
    ]
    return (
        translate_for_user(
            telegram_user_id,
            "admin.screen.user.title",
            display_name=user["display_name"],
            telegram_user_id=user["telegram_user_id"],
            role=translate_for_user(
                telegram_user_id,
                f"admin.role.{user['role']}",
            ),
            default_teacher_workspace=translate_for_user(
                telegram_user_id,
                "common.yes" if user["has_default_teacher_workspace"] else "common.no",
            ),
            default_student_workspace=translate_for_user(
                telegram_user_id,
                "common.yes" if user["has_default_student_workspace"] else "common.no",
            ),
            workspace_lines="\n".join(workspace_lines)
            if workspace_lines
            else translate_for_user(telegram_user_id, "admin.screen.user.no_workspaces"),
        ),
        _build_user_detail_keyboard(telegram_user_id, target_user_id, page),
    )


async def _edit_admin_screen(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if callback.message is None:
        return
    await callback.message.edit_text(text, reply_markup=reply_markup)


@router.message(Command(ADMIN_COMMAND.name))
async def open_admin(message: Message) -> None:
    if message.from_user is None:
        return

    save_user(message.from_user)
    try:
        ensure_admin_access(message.from_user.id)
    except AdminAccessDeniedError:
        await message.answer(
            translate_for_user(message.from_user.id, "admin.command_admin_only")
        )
        return

    text, reply_markup = _render_users_screen(message.from_user.id, page=0)
    await message.answer(text, reply_markup=reply_markup)


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("admin:"))
async def handle_admin_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return

    try:
        ensure_admin_access(callback.from_user.id)
    except AdminAccessDeniedError:
        await callback.answer(
            translate_for_user(callback.from_user.id, "admin.command_admin_only"),
            show_alert=True,
        )
        return

    parts = callback.data.split(":")
    try:
        if parts[1] == "page":
            page = int(parts[2])
            text, reply_markup = _render_users_screen(callback.from_user.id, page)
            await _edit_admin_screen(callback, text, reply_markup)
            await callback.answer()
            return

        if parts[1] == "user":
            target_user_id = int(parts[2])
            page = int(parts[3])
            text, reply_markup = _render_user_screen(
                callback.from_user.id,
                target_user_id,
                page,
            )
            await _edit_admin_screen(callback, text, reply_markup)
            await callback.answer()
            return

        if parts[1] == "act":
            target_user_id = int(parts[2])
            action = parts[3]
            page = int(parts[4])
            result_message = await _apply_admin_action(
                callback.from_user.id,
                target_user_id,
                action,
            )
            text, reply_markup = _render_user_screen(
                callback.from_user.id,
                target_user_id,
                page,
            )
            await _edit_admin_screen(callback, text, reply_markup)
            await callback.answer(result_message)
            return
    except (IndexError, ValueError, RegisteredUserNotFoundError):
        await callback.answer(
            translate_for_user(callback.from_user.id, "admin.user.not_found"),
            show_alert=True,
        )
        return

    await callback.answer()


async def _apply_admin_action(
    actor_user_id: int,
    target_user_id: int,
    action: str,
) -> str:
    get_registered_user_for_admin(actor_user_id, target_user_id)
    if action == "make_teacher":
        grant_teacher_role(target_user_id)
        ensure_default_spaces_for_user(target_user_id)
        return translate_for_user(actor_user_id, "admin.result.make_teacher")
    if action == "keep_student":
        keep_student_role(target_user_id)
        ensure_default_spaces_for_user(target_user_id)
        return translate_for_user(actor_user_id, "admin.result.keep_student")
    if action == "create_default_spaces":
        ensure_default_spaces_for_user(target_user_id)
        return translate_for_user(actor_user_id, "admin.result.create_default_spaces")
    if action == "link_family_teacher":
        family_workspace = ensure_shared_family_workspace()
        add_user_to_student_workspace(
            int(family_workspace["workspace_id"]),
            target_user_id,
            ROLE_TEACHER,
        )
        return translate_for_user(
            actor_user_id,
            "admin.result.link_family_teacher",
            workspace_name=family_workspace["name"],
        )
    if action == "link_family_student":
        family_workspace = ensure_shared_family_workspace()
        add_user_to_student_workspace(
            int(family_workspace["workspace_id"]),
            target_user_id,
            ROLE_STUDENT,
        )
        return translate_for_user(
            actor_user_id,
            "admin.result.link_family_student",
            workspace_name=family_workspace["name"],
        )
    raise RegisteredUserNotFoundError
