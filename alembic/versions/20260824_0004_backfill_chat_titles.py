"""Backfill chat session titles

Revision ID: 20260824_0004
Revises: 20260824_0003
Create Date: 2026-08-24 21:25:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0004"
down_revision = "20260824_0003"
branch_labels = None
depends_on = None


def _title_from_message(message: str) -> str:
    normalized = " ".join((message or "").strip().split())
    if not normalized:
        return "Nova conversa"

    sentence_positions = [position for marker in [".", "?", "!"] if (position := normalized.find(marker)) != -1]
    if sentence_positions:
        normalized = normalized[: min(sentence_positions) + 1]

    if len(normalized) <= 56:
        return normalized
    return f"{normalized[:53].rstrip()}..."


def upgrade() -> None:
    connection = op.get_bind()
    sessions = connection.execute(
        sa.text(
            """
            SELECT id, title
            FROM chat_sessions
            WHERE title = 'Nova conversa'
               OR title LIKE 'Conversa sobre %'
            """
        )
    ).mappings()

    for session in sessions:
        first_user_message = connection.execute(
            sa.text(
                """
                SELECT content
                FROM chat_messages
                WHERE session_id = :session_id
                  AND role = 'user'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"session_id": session["id"]},
        ).scalar()
        if not first_user_message:
            continue
        connection.execute(
            sa.text("UPDATE chat_sessions SET title = :title WHERE id = :session_id"),
            {"title": _title_from_message(first_user_message), "session_id": session["id"]},
        )


def downgrade() -> None:
    pass
