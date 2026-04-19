import secrets
import sqlite3

from .db import get_connection, get_default_content_workspace_id, get_user, utc_now
from .user_profiles import get_user_role
from .workspaces import add_workspace_member


ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
class TeacherStudentError(Exception):
    pass


class TeacherRoleRequiredError(TeacherStudentError):
    pass


class InviteNotFoundError(TeacherStudentError):
    pass


class InviteAlreadyUsedError(TeacherStudentError):
    pass


class StudentAlreadyLinkedError(TeacherStudentError):
    pass


def create_invite(teacher_user_id: int) -> str:
    teacher = get_user(teacher_user_id)
    if teacher is None or get_user_role(teacher_user_id) != ROLE_TEACHER:
        raise TeacherRoleRequiredError

    code = secrets.token_hex(4).upper()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO invites (code, teacher_user_id, created_at)
            VALUES (?, ?, ?)
            """,
            (code, teacher_user_id, utc_now()),
        )
    return code


def join_with_invite(student_user_id: int, code: str) -> int:
    normalized_code = code.strip().upper()
    with get_connection() as connection:
        invite = connection.execute(
            """
            SELECT id, teacher_user_id, used_at
            FROM invites
            WHERE code = ?
            """,
            (normalized_code,),
        ).fetchone()
        if invite is None:
            raise InviteNotFoundError
        if invite["used_at"] is not None:
            raise InviteAlreadyUsedError

        existing_link = connection.execute(
            """
            SELECT teacher_user_id
            FROM teacher_student_links
            WHERE student_user_id = ?
            """,
            (student_user_id,),
        ).fetchone()
        if existing_link is not None:
            raise StudentAlreadyLinkedError

        timestamp = utc_now()
        connection.execute(
            """
            INSERT INTO teacher_student_links (
                teacher_user_id,
                student_user_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (invite["teacher_user_id"], student_user_id, timestamp),
        )
        connection.execute(
            """
            UPDATE invites
            SET used_by_user_id = ?, used_at = ?
            WHERE id = ?
            """,
            (student_user_id, timestamp, invite["id"]),
        )

    workspace_id = get_default_content_workspace_id()
    add_workspace_member(workspace_id, int(invite["teacher_user_id"]), ROLE_TEACHER)
    if student_user_id != int(invite["teacher_user_id"]):
        add_workspace_member(workspace_id, student_user_id, ROLE_STUDENT)
    return int(invite["teacher_user_id"])


def get_teacher_link(student_user_id: int) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT teacher_user_id, student_user_id, created_at
            FROM teacher_student_links
            WHERE student_user_id = ?
            """,
            (student_user_id,),
        ).fetchone()


def get_invite(code: str) -> sqlite3.Row | None:
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT code, teacher_user_id, used_by_user_id, created_at, used_at
            FROM invites
            WHERE code = ?
            """,
            (code.strip().upper(),),
        ).fetchone()
