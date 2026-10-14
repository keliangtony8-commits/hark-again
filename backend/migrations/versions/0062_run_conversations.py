"""v2.75 运行对话不进列表：conversations.task_id（app/run_conversations.py 规则）。
回填：运行记录或报告卡指着的对话、标题以“面板 · ”开头且没人接话的对话，标成对应任务的运行对话。

Revision ID: 0062
Revises: 0061
"""
from alembic import op
import sqlalchemy as sa

revision = '0062'
down_revision = '0061'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('task_id', sa.String(32), nullable=True))
    op.create_index('ix_conversations_task_id', 'conversations', ['task_id'])
    # 只回填用户没接过话的（只有任务那一句 user 消息）：接过话的已经是用户自己的对话
    untouched = ("(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = conversations.id AND m.role = 'user') <= 1")
    op.execute("UPDATE conversations SET task_id = (SELECT r.task_id FROM task_runs r WHERE r.conversation_id = conversations.id "
               "LIMIT 1) WHERE task_id IS NULL AND EXISTS (SELECT 1 FROM task_runs r WHERE r.conversation_id = conversations.id) "
               f"AND {untouched}")
    op.execute("UPDATE conversations SET task_id = (SELECT c.task_id FROM home_cards c WHERE c.conversation_id = conversations.id "
               "AND c.kind = 'report' AND c.task_id IS NOT NULL LIMIT 1) WHERE task_id IS NULL AND EXISTS (SELECT 1 FROM home_cards c "
               f"WHERE c.conversation_id = conversations.id AND c.kind = 'report' AND c.task_id IS NOT NULL) AND {untouched}")


def downgrade() -> None:
    op.drop_index('ix_conversations_task_id', 'conversations')
    op.drop_column('conversations', 'task_id')
