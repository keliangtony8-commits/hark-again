"""v2.21 记忆笔记（app/memory_notes.py）：一个主题一篇 Markdown。

Revision ID: 0054
Revises: 0053
"""
from alembic import op
import sqlalchemy as sa

revision = '0054'
down_revision = '0053'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memory_notes',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('path', sa.String(120), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False, server_default='misc'),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_memory_notes_path', 'memory_notes', ['path'])


def downgrade() -> None:
    op.drop_index('ix_memory_notes_path', 'memory_notes')
    op.drop_table('memory_notes')
