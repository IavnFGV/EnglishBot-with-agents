import sqlite3

from . import db


class FamilyMembershipError(ValueError):
    pass


class FamilyOwnershipError(ValueError):
    pass


DEMO_FAMILY_TOPICS: tuple[dict[str, object], ...] = (
    {
        "name": "seasons",
        "title": "Seasons",
        "items": (
            {"text": "spring", "translations": {"ru": "весна", "uk": "весна", "bg": "пролет"}},
            {"text": "summer", "translations": {"ru": "лето", "uk": "літо", "bg": "лято"}},
            {"text": "autumn", "translations": {"ru": "осень", "uk": "осінь", "bg": "есен"}},
            {"text": "winter", "translations": {"ru": "зима", "uk": "зима", "bg": "зима"}},
        ),
    },
    {
        "name": "colors",
        "title": "Colors",
        "items": (
            {"text": "red", "translations": {"ru": "красный", "uk": "червоний", "bg": "червен"}},
            {"text": "blue", "translations": {"ru": "синий", "uk": "синій", "bg": "син"}},
            {"text": "green", "translations": {"ru": "зеленый", "uk": "зелений", "bg": "зелен"}},
            {"text": "yellow", "translations": {"ru": "желтый", "uk": "жовтий", "bg": "жълт"}},
            {"text": "black", "translations": {"ru": "черный", "uk": "чорний", "bg": "черен"}},
            {"text": "white", "translations": {"ru": "белый", "uk": "білий", "bg": "бял"}},
        ),
    },
)


def create_family(name: str, created_by_user_id: int) -> sqlite3.Row:
    db.ensure_user_exists(created_by_user_id)
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO families (
                name,
                created_by_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), created_by_user_id, timestamp, timestamp),
        )
        family_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO family_members (
                family_id,
                telegram_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (family_id, created_by_user_id, timestamp, timestamp),
        )
        return _get_family(connection, family_id)


def _get_family(connection: sqlite3.Connection, family_id: int) -> sqlite3.Row:
    family = connection.execute(
        """
        SELECT id, name, created_by_user_id, created_at, updated_at
        FROM families
        WHERE id = ?
        """,
        (family_id,),
    ).fetchone()
    assert family is not None
    return family


def get_family(family_id: int) -> sqlite3.Row | None:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, created_by_user_id, created_at, updated_at
            FROM families
            WHERE id = ?
            """,
            (family_id,),
        ).fetchone()


def get_user_family(telegram_user_id: int) -> sqlite3.Row | None:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT
                families.id,
                families.name,
                families.created_by_user_id,
                families.created_at,
                families.updated_at
            FROM families
            JOIN family_members
              ON family_members.family_id = families.id
            WHERE family_members.telegram_user_id = ?
            LIMIT 1
            """,
            (telegram_user_id,),
        ).fetchone()


def add_family_member(family_id: int, telegram_user_id: int) -> None:
    db.ensure_user_exists(telegram_user_id)
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        existing = connection.execute(
            """
            SELECT family_id
            FROM family_members
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()
        if existing is not None and int(existing["family_id"]) != family_id:
            raise FamilyMembershipError("user already belongs to another family")
        connection.execute(
            """
            INSERT OR IGNORE INTO family_members (
                family_id,
                telegram_user_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (family_id, telegram_user_id, timestamp, timestamp),
        )


def ensure_user_family(owner_user_id: int, default_family_name: str = "Home") -> sqlite3.Row:
    family = get_user_family(owner_user_id)
    if family is not None:
        return family
    return create_family(default_family_name, owner_user_id)


def add_user_to_owner_family(owner_user_id: int, target_user_id: int) -> tuple[sqlite3.Row, str]:
    owner_family = ensure_user_family(owner_user_id)
    target_family = get_user_family(target_user_id)
    if target_family is not None:
        if int(target_family["id"]) == int(owner_family["id"]):
            return owner_family, "already_member"
        raise FamilyMembershipError("user already belongs to another family")
    add_family_member(int(owner_family["id"]), target_user_id)
    return owner_family, "added"


def seed_demo_family_content(owner_user_id: int) -> dict[str, object]:
    from .topics import get_topic
    from .vocabulary import (
        create_learning_item_translation,
        create_lexeme,
        list_learning_item_translations,
    )

    family = ensure_user_family(owner_user_id)
    family_id = int(family["id"])
    existing_items = {
        str(item["text"]).strip().lower(): int(item["id"])
        for item in list_family_learning_items(family_id)
    }
    existing_topics = {
        str(topic["name"]).strip().lower(): int(topic["id"])
        for topic in list_family_topics(family_id)
    }
    created_topics = 0
    created_items = 0

    for topic_seed in DEMO_FAMILY_TOPICS:
        topic_name = str(topic_seed["name"]).strip().lower()
        topic_id = existing_topics.get(topic_name)
        if topic_id is None:
            topic_id = create_family_topic(family_id, topic_name, str(topic_seed["title"]))
            existing_topics[topic_name] = topic_id
            created_topics += 1

        topic_item_ids: list[int] = []
        for item_seed in topic_seed["items"]:
            item_text = str(item_seed["text"]).strip()
            item_key = item_text.lower()
            learning_item_id = existing_items.get(item_key)
            if learning_item_id is None:
                learning_item_id = create_family_learning_item(
                    family_id,
                    create_lexeme(item_text),
                    item_text,
                )
                existing_items[item_key] = learning_item_id
                created_items += 1

            existing_translations = {
                str(row["language_code"]): str(row["translation_text"])
                for row in list_learning_item_translations(learning_item_id)
            }
            for language_code, translation_text in dict(item_seed["translations"]).items():
                if existing_translations.get(language_code) != translation_text:
                    create_learning_item_translation(
                        learning_item_id,
                        language_code,
                        str(translation_text),
                    )
            topic_item_ids.append(learning_item_id)

        replace_topic_items(topic_id, topic_item_ids)

    total_topics = len(DEMO_FAMILY_TOPICS)
    total_items = sum(len(topic_seed["items"]) for topic_seed in DEMO_FAMILY_TOPICS)
    return {
        "family_id": family_id,
        "family_name": str(family["name"] or "Home"),
        "created_topics": created_topics,
        "created_items": created_items,
        "total_topics": total_topics,
        "total_items": total_items,
    }


def list_family_members(family_id: int) -> list[sqlite3.Row]:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT users.telegram_user_id, users.username, users.first_name, users.last_name
            FROM family_members
            JOIN users
              ON users.telegram_user_id = family_members.telegram_user_id
            WHERE family_members.family_id = ?
            ORDER BY users.first_name, users.telegram_user_id
            """,
            (family_id,),
        ).fetchall()


def create_family_learning_item(
    family_id: int,
    lexeme_id: int,
    text: str,
) -> int:
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO learning_items (
                family_id,
                lexeme_id,
                text,
                is_archived,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (
                family_id,
                lexeme_id,
                text,
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def list_family_learning_items(family_id: int) -> list[sqlite3.Row]:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT id, family_id, lexeme_id, text, is_archived, created_at, updated_at
            FROM learning_items
            WHERE family_id = ?
              AND is_archived = 0
            ORDER BY id
            """,
            (family_id,),
        ).fetchall()


def create_family_topic(family_id: int, name: str, title: str) -> int:
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO topics (
                family_id,
                name,
                title,
                is_archived,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (
                family_id,
                name.strip(),
                title.strip(),
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def replace_topic_items(topic_id: int, learning_item_ids: list[int]) -> None:
    with db.get_connection() as connection:
        topic = connection.execute(
            """
            SELECT family_id
            FROM topics
            WHERE id = ?
            """,
            (topic_id,),
        ).fetchone()
        if topic is None:
            raise FamilyOwnershipError("topic not found")
        family_id = int(topic["family_id"]) if topic["family_id"] is not None else None
        if family_id is None:
            raise FamilyOwnershipError("topic is not family-owned")
        for learning_item_id in learning_item_ids:
            item = connection.execute(
                """
                SELECT family_id
                FROM learning_items
                WHERE id = ?
                """,
                (learning_item_id,),
            ).fetchone()
            if item is None or item["family_id"] is None or int(item["family_id"]) != family_id:
                raise FamilyOwnershipError("learning item does not belong to the same family")
        connection.execute(
            """
            DELETE FROM topic_items
            WHERE topic_id = ?
            """,
            (topic_id,),
        )
        for item_order, learning_item_id in enumerate(learning_item_ids):
            connection.execute(
                """
                INSERT INTO topic_items (
                    topic_id,
                    learning_item_id
                )
                VALUES (?, ?)
                """,
                (topic_id, learning_item_id),
            )


def list_family_topics(family_id: int) -> list[sqlite3.Row]:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT id, family_id, name, title, is_archived, created_at, updated_at
            FROM topics
            WHERE family_id = ?
              AND is_archived = 0
            ORDER BY title, id
            """,
            (family_id,),
        ).fetchall()


def create_homework_assignment(
    family_id: int,
    assigned_by_user_id: int,
    assigned_to_user_id: int,
    learning_item_ids: list[int],
    *,
    title: str | None = None,
) -> int:
    db.ensure_user_exists(assigned_by_user_id)
    db.ensure_user_exists(assigned_to_user_id)
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        family_member_ids = {
            int(row["telegram_user_id"])
            for row in connection.execute(
                """
                SELECT telegram_user_id
                FROM family_members
                WHERE family_id = ?
                """,
                (family_id,),
            ).fetchall()
        }
        if assigned_by_user_id not in family_member_ids or assigned_to_user_id not in family_member_ids:
            raise FamilyMembershipError("homework users must belong to the family")
        for learning_item_id in learning_item_ids:
            item = connection.execute(
                """
                SELECT family_id
                FROM learning_items
                WHERE id = ?
                """,
                (learning_item_id,),
            ).fetchone()
            if item is None or item["family_id"] is None or int(item["family_id"]) != family_id:
                raise FamilyOwnershipError("homework item does not belong to the family")
        cursor = connection.execute(
            """
            INSERT INTO homework_assignments (
                family_id,
                assigned_by_user_id,
                assigned_to_user_id,
                title,
                status,
                created_at,
                updated_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
            """,
            (family_id, assigned_by_user_id, assigned_to_user_id, title, timestamp, timestamp),
        )
        assignment_id = int(cursor.lastrowid)
        for item_order, learning_item_id in enumerate(learning_item_ids):
            connection.execute(
                """
                INSERT INTO homework_assignment_items (
                    homework_assignment_id,
                    learning_item_id,
                    item_order
                )
                VALUES (?, ?, ?)
                """,
                (assignment_id, learning_item_id, item_order),
            )
        return assignment_id


def get_homework_assignment(assignment_id: int) -> sqlite3.Row | None:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                family_id,
                assigned_by_user_id,
                assigned_to_user_id,
                title,
                status,
                created_at,
                updated_at,
                completed_at
            FROM homework_assignments
            WHERE id = ?
            """,
            (assignment_id,),
        ).fetchone()


def upsert_user_progress(
    telegram_user_id: int,
    learning_item_id: int,
    *,
    status: str,
    correct_streak: int = 0,
) -> None:
    db.ensure_user_exists(telegram_user_id)
    timestamp = db.utc_now()
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_progress (
                telegram_user_id,
                learning_item_id,
                status,
                correct_streak,
                last_answered_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (telegram_user_id, learning_item_id) DO UPDATE SET
                status = excluded.status,
                correct_streak = excluded.correct_streak,
                last_answered_at = excluded.last_answered_at,
                updated_at = excluded.updated_at
            """,
            (
                telegram_user_id,
                learning_item_id,
                status,
                correct_streak,
                timestamp,
                timestamp,
                timestamp,
            ),
        )


def get_user_progress(telegram_user_id: int, learning_item_id: int) -> sqlite3.Row | None:
    with db.get_connection() as connection:
        return connection.execute(
            """
            SELECT
                telegram_user_id,
                learning_item_id,
                status,
                correct_streak,
                last_answered_at,
                created_at,
                updated_at
            FROM user_progress
            WHERE telegram_user_id = ?
              AND learning_item_id = ?
            """,
            (telegram_user_id, learning_item_id),
        ).fetchone()
