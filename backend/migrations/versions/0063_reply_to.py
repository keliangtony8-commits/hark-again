"""v2.87 引用回复：messages.reply_to（app/reply_quote.py 规则；home-redesign §J 用户侧 + §C 后台结果共用这一列）。

Revision ID: 0063
Revises: 0062
"""
from alembic import op
import sqlalchemy as sa

revision = '0063'
down_revision = '0062'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('reply_to', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'reply_to')
