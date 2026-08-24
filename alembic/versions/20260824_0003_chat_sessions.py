"""Chat sessions

Revision ID: 20260824_0003
Revises: 20260824_0002
Create Date: 2026-08-24 21:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0003"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fault", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_sessions_created_at", "chat_sessions", ["created_at"])
    op.create_index("ix_chat_sessions_updated_at", "chat_sessions", ["updated_at"])
    op.create_index("ix_chat_sessions_analysis_id", "chat_sessions", ["analysis_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_analysis_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_updated_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_created_at", table_name="chat_sessions")
    op.drop_table("chat_sessions")
