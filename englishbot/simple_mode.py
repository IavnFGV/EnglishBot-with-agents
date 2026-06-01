import sqlite3

from .config import is_simple_mode_enabled
from .db import get_connection
from .user_profiles import set_user_role
from .workspaces import (
    ROLE_TEACHER,
    WORKSPACE_KIND_STUDENT,
    WORKSPACE_KIND_TEACHER,
    add_workspace_member,
    create_workspace,
    get_workspace,
)


SIMPLE_MODE_TEACHER_WORKSPACE_NAME = "Family Teacher Workspace"
SIMPLE_MODE_STUDENT_WORKSPACE_NAME = "Family Student Workspace"


def ensure_simple_mode_user(telegram_user_id: int) -> None:
    if not is_simple_mode_enabled():
        return

    set_user_role(telegram_user_id, ROLE_TEACHER)
    teacher_workspace_id = get_simple_mode_teacher_workspace_id()
    student_workspace_id = get_simple_mode_student_workspace_id()
    add_workspace_member(teacher_workspace_id, telegram_user_id, ROLE_TEACHER)
    add_workspace_member(student_workspace_id, telegram_user_id, ROLE_TEACHER)


def get_simple_mode_teacher_workspace_id() -> int:
    return _get_or_create_workspace_id(
        name=SIMPLE_MODE_TEACHER_WORKSPACE_NAME,
        kind=WORKSPACE_KIND_TEACHER,
    )


def get_simple_mode_student_workspace_id() -> int:
    return _get_or_create_workspace_id(
        name=SIMPLE_MODE_STUDENT_WORKSPACE_NAME,
        kind=WORKSPACE_KIND_STUDENT,
    )


def get_simple_mode_teacher_workspace() -> sqlite3.Row:
    workspace = get_workspace(get_simple_mode_teacher_workspace_id())
    if workspace is None:
        raise RuntimeError("Simple mode teacher workspace is missing")
    return workspace


def get_simple_mode_student_workspace() -> sqlite3.Row:
    workspace = get_workspace(get_simple_mode_student_workspace_id())
    if workspace is None:
        raise RuntimeError("Simple mode student workspace is missing")
    return workspace


def list_simple_mode_student_user_ids() -> list[int]:
    workspace_id = get_simple_mode_student_workspace_id()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT telegram_user_id
            FROM workspace_members
            WHERE workspace_id = ?
            ORDER BY telegram_user_id
            """,
            (workspace_id,),
        ).fetchall()
    return [int(row["telegram_user_id"]) for row in rows]


def get_simple_mode_runtime_workspace_id() -> int:
    return get_simple_mode_student_workspace_id()


def _get_or_create_workspace_id(*, name: str, kind: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM workspaces
            WHERE name = ? AND kind = ?
            ORDER BY id
            LIMIT 1
            """,
            (name, kind),
        ).fetchone()
    if row is not None:
        return int(row["id"])

    workspace = create_workspace(name=name, kind=kind)
    return int(workspace["workspace_id"])
