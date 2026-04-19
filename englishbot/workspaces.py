import sqlite3

from .db import ensure_user_exists, get_connection, utc_now


ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
WORKSPACE_ROLE_VALUES = {ROLE_TEACHER, ROLE_STUDENT}


class WorkspaceError(Exception):
    pass


class InvalidWorkspaceRoleError(WorkspaceError):
    pass


class WorkspaceNotFoundError(WorkspaceError):
    pass


def create_workspace(name: str | None = None) -> dict[str, object]:
    stored_name = None if name is None or not name.strip() else name.strip()
    created_at = utc_now()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO workspaces (name, created_at)
            VALUES (?, ?)
            """,
            (stored_name, created_at),
        )

    return {
        "workspace_id": int(cursor.lastrowid),
        "name": stored_name,
        "created_at": created_at,
    }


def add_workspace_member(
    workspace_id: int,
    telegram_user_id: int,
    role: str,
) -> dict[str, object]:
    normalized_role = _normalize_workspace_role(role)

    timestamp = utc_now()
    with get_connection() as connection:
        workspace = connection.execute(
            """
            SELECT id
            FROM workspaces
            WHERE id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            raise WorkspaceNotFoundError
        ensure_user_exists(telegram_user_id)

        connection.execute(
            """
            INSERT INTO workspace_members (
                workspace_id,
                telegram_user_id,
                role,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, telegram_user_id) DO UPDATE SET
                role = excluded.role,
                updated_at = excluded.updated_at
            """,
            (
                workspace_id,
                telegram_user_id,
                normalized_role,
                timestamp,
                timestamp,
            ),
        )

    return {
        "workspace_id": workspace_id,
        "telegram_user_id": telegram_user_id,
        "role": normalized_role,
    }


def list_workspaces_for_user(telegram_user_id: int) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                workspaces.id,
                workspaces.name,
                workspaces.created_at,
                workspace_members.role
            FROM workspace_members
            JOIN workspaces
              ON workspaces.id = workspace_members.workspace_id
            WHERE workspace_members.telegram_user_id = ?
            ORDER BY workspaces.id
            """,
            (telegram_user_id,),
        ).fetchall()


def find_workspaces_for_user_by_role(
    telegram_user_id: int,
    role: str,
) -> list[sqlite3.Row]:
    normalized_role = _normalize_workspace_role(role)
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                workspaces.id,
                workspaces.name,
                workspaces.created_at,
                workspace_members.role
            FROM workspace_members
            JOIN workspaces
              ON workspaces.id = workspace_members.workspace_id
            WHERE workspace_members.telegram_user_id = ?
              AND workspace_members.role = ?
            ORDER BY workspaces.id
            """,
            (telegram_user_id, normalized_role),
        ).fetchall()


def get_workspace_member(
    workspace_id: int,
    telegram_user_id: int,
) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                workspace_id,
                telegram_user_id,
                role,
                created_at,
                updated_at
            FROM workspace_members
            WHERE workspace_id = ? AND telegram_user_id = ?
            """,
            (workspace_id, telegram_user_id),
        ).fetchone()


def user_is_workspace_member(
    workspace_id: int,
    telegram_user_id: int,
    role: str | None = None,
) -> bool:
    membership = get_workspace_member(workspace_id, telegram_user_id)
    if membership is None:
        return False
    if role is None:
        return True
    return str(membership["role"]) == _normalize_workspace_role(role)


def find_shared_workspace_for_teacher_and_student(
    teacher_user_id: int,
    student_user_id: int,
) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                workspaces.id,
                workspaces.name,
                workspaces.created_at
            FROM workspace_members AS teacher_membership
            JOIN workspace_members AS student_membership
              ON student_membership.workspace_id = teacher_membership.workspace_id
            JOIN workspaces
              ON workspaces.id = teacher_membership.workspace_id
            WHERE teacher_membership.telegram_user_id = ?
              AND teacher_membership.role = ?
              AND student_membership.telegram_user_id = ?
            ORDER BY workspaces.id
            LIMIT 1
            """,
            (teacher_user_id, ROLE_TEACHER, student_user_id),
        ).fetchone()


def _normalize_workspace_role(role: str) -> str:
    if not isinstance(role, str):
        raise InvalidWorkspaceRoleError
    normalized_role = role.strip().lower()
    if normalized_role not in WORKSPACE_ROLE_VALUES:
        raise InvalidWorkspaceRoleError
    return normalized_role
