"""v2.90 §C 欠回复账本：messages.answered_by = 结清这条用户消息的那条回复的 id（app/message_intake.py 规则）。

Revision ID: 0064
Revises: 0063
"""
from alembic import op
import sqlalchemy as sa

revision = '0064'
down_revision = '0063'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('answered_by', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'answered_by')
