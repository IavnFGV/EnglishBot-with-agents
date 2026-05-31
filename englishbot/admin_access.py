import sqlite3

from .config import get_admin_telegram_user_id
from .db import ensure_user_exists, get_connection, get_user
from .user_profiles import get_user_role, set_user_role
from .workspaces import (
    ROLE_STUDENT,
    ROLE_TEACHER,
    WORKSPACE_KIND_STUDENT,
    WORKSPACE_KIND_TEACHER,
    add_workspace_member,
    create_workspace,
    ensure_workspace_kind,
    list_workspaces_for_user,
)


PERSONAL_TEACHER_WORKSPACE_NAME_TEMPLATE = "Teacher Workspace {telegram_user_id}"
PERSONAL_STUDENT_WORKSPACE_NAME_TEMPLATE = "Student Workspace {telegram_user_id}"
SHARED_FAMILY_WORKSPACE_NAME = "Family Workspace"


class AdminAccessError(Exception):
    pass


class AdminAccessDeniedError(AdminAccessError):
    pass


class RegisteredUserNotFoundError(AdminAccessError):
    pass


def ensure_admin_access(telegram_user_id: int) -> int:
    admin_user_id = get_admin_telegram_user_id()
    if admin_user_id is None or int(telegram_user_id) != admin_user_id:
        raise AdminAccessDeniedError
    return admin_user_id


def list_registered_users_for_admin(admin_user_id: int) -> list[dict[str, object]]:
    ensure_admin_access(admin_user_id)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                users.telegram_user_id,
                users.username,
                users.first_name,
                users.last_name,
                users.created_at,
                users.updated_at,
                user_profiles.role
            FROM users
            JOIN user_profiles
              ON user_profiles.telegram_user_id = users.telegram_user_id
            ORDER BY users.created_at, users.telegram_user_id
            """
        ).fetchall()
    return [_build_registered_user_summary(row) for row in rows]


def get_registered_user_for_admin(
    admin_user_id: int,
    telegram_user_id: int,
) -> dict[str, object]:
    ensure_admin_access(admin_user_id)
    user = get_user(telegram_user_id)
    if user is None:
        raise RegisteredUserNotFoundError
    profile_row = {
        "telegram_user_id": telegram_user_id,
        "username": user["username"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "created_at": user["created_at"],
        "updated_at": user["updated_at"],
        "role": get_user_role(telegram_user_id),
    }
    return _build_registered_user_summary(profile_row)


def ensure_default_spaces_for_user(telegram_user_id: int) -> dict[str, int]:
    ensure_user_exists(telegram_user_id)
    teacher_workspace_id = _ensure_personal_workspace(
        telegram_user_id,
        kind=WORKSPACE_KIND_TEACHER,
        role=ROLE_TEACHER,
        name=PERSONAL_TEACHER_WORKSPACE_NAME_TEMPLATE.format(
            telegram_user_id=telegram_user_id,
        ),
    )
    student_workspace_id = _ensure_personal_workspace(
        telegram_user_id,
        kind=WORKSPACE_KIND_STUDENT,
        role=ROLE_STUDENT,
        name=PERSONAL_STUDENT_WORKSPACE_NAME_TEMPLATE.format(
            telegram_user_id=telegram_user_id,
        ),
    )
    return {
        "teacher_workspace_id": teacher_workspace_id,
        "student_workspace_id": student_workspace_id,
    }


def grant_teacher_role(telegram_user_id: int) -> None:
    ensure_user_exists(telegram_user_id)
    set_user_role(telegram_user_id, ROLE_TEACHER)


def keep_student_role(telegram_user_id: int) -> None:
    ensure_user_exists(telegram_user_id)
    set_user_role(telegram_user_id, ROLE_STUDENT)


def add_user_to_student_workspace(
    workspace_id: int,
    telegram_user_id: int,
    role: str = ROLE_STUDENT,
) -> dict[str, object]:
    ensure_workspace_kind(workspace_id, WORKSPACE_KIND_STUDENT)
    return add_workspace_member(workspace_id, telegram_user_id, role)


def ensure_shared_family_workspace() -> dict[str, object]:
    with get_connection() as connection:
        workspace = connection.execute(
            """
            SELECT id, name, kind, created_at
            FROM workspaces
            WHERE kind = ? AND name = ?
            ORDER BY id
            LIMIT 1
            """,
            (WORKSPACE_KIND_STUDENT, SHARED_FAMILY_WORKSPACE_NAME),
        ).fetchone()
    if workspace is not None:
        return {
            "workspace_id": int(workspace["id"]),
            "name": str(workspace["name"]),
            "kind": str(workspace["kind"]),
        }

    created = create_workspace(
        name=SHARED_FAMILY_WORKSPACE_NAME,
        kind=WORKSPACE_KIND_STUDENT,
    )
    return {
        "workspace_id": int(created["workspace_id"]),
        "name": str(created["name"]),
        "kind": str(created["kind"]),
    }


def _ensure_personal_workspace(
    telegram_user_id: int,
    *,
    kind: str,
    role: str,
    name: str,
) -> int:
    with get_connection() as connection:
        workspace = connection.execute(
            """
            SELECT workspaces.id
            FROM workspace_members
            JOIN workspaces
              ON workspaces.id = workspace_members.workspace_id
            WHERE workspace_members.telegram_user_id = ?
              AND workspace_members.role = ?
              AND workspaces.kind = ?
              AND workspaces.name = ?
            ORDER BY workspaces.id
            LIMIT 1
            """,
            (telegram_user_id, role, kind, name),
        ).fetchone()
    if workspace is not None:
        return int(workspace["id"])

    created = create_workspace(name=name, kind=kind)
    add_workspace_member(int(created["workspace_id"]), telegram_user_id, role)
    return int(created["workspace_id"])


def _build_registered_user_summary(row: sqlite3.Row | dict[str, object]) -> dict[str, object]:
    telegram_user_id = int(row["telegram_user_id"])
    workspaces = list_workspaces_for_user(telegram_user_id)
    return {
        "telegram_user_id": telegram_user_id,
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "display_name": _build_display_name(row),
        "role": str(row["role"] or ROLE_STUDENT),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "workspaces": [
            {
                "id": int(workspace["id"]),
                "name": workspace["name"],
                "kind": str(workspace["kind"]),
                "role": str(workspace["role"]),
            }
            for workspace in workspaces
        ],
        "has_default_teacher_workspace": any(
            str(workspace["kind"]) == WORKSPACE_KIND_TEACHER
            and str(workspace["role"]) == ROLE_TEACHER
            and str(workspace["name"] or "")
            == PERSONAL_TEACHER_WORKSPACE_NAME_TEMPLATE.format(
                telegram_user_id=telegram_user_id,
            )
            for workspace in workspaces
        ),
        "has_default_student_workspace": any(
            str(workspace["kind"]) == WORKSPACE_KIND_STUDENT
            and str(workspace["role"]) == ROLE_STUDENT
            and str(workspace["name"] or "")
            == PERSONAL_STUDENT_WORKSPACE_NAME_TEMPLATE.format(
                telegram_user_id=telegram_user_id,
            )
            for workspace in workspaces
        ),
    }


def _build_display_name(row: sqlite3.Row | dict[str, object]) -> str:
    first_name = str(row["first_name"] or "").strip()
    last_name = str(row["last_name"] or "").strip()
    username = str(row["username"] or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    if full_name:
        return full_name
    if username:
        return f"@{username}"
    return str(row["telegram_user_id"])
