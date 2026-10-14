"""v2.91 §N 总结标题定期复查：conversations.title_at = 上次起标题时这段对话有几条消息（app/conversation_title.py 规则）。
已有的 auto 标题回填为当前消息数：升级后老对话不会立刻被改名，再多约 10 条才复查。

Revision ID: 0065
Revises: 0064
"""
from alembic import op
import sqlalchemy as sa

revision = '0065'
down_revision = '0064'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('title_at', sa.Integer(), nullable=True))
    op.execute("UPDATE conversations SET title_at = (SELECT count(*) FROM messages WHERE messages.conversation_id = conversations.id) "
               "WHERE title_source = 'auto'")


def downgrade() -> None:
    op.drop_column('conversations', 'title_at')
