"""子助手的上下文（v1.97，app/agent/subagent_threads.py）：subagent_threads 表，子任务结束后留下它的消息列表，
按 id 冷恢复续问（Codex resume_agent）。

Revision ID: 0046
Revises: 0045
"""
from alembic import op
import sqlalchemy as sa

revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'subagent_threads',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('conversation_id', sa.String(32), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(64), nullable=False),
        sa.Column('model', sa.String(64), nullable=True),
        sa.Column('history', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('state', sa.String(16), nullable=False, server_default='done'),
        sa.Column('rounds', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_subagent_threads_conversation_id', 'subagent_threads', ['conversation_id'])
    op.create_index('ix_subagent_threads_updated_at', 'subagent_threads', ['updated_at'])


def downgrade() -> None:
    op.drop_index('ix_subagent_threads_updated_at', 'subagent_threads')
    op.drop_index('ix_subagent_threads_conversation_id', 'subagent_threads')
    op.drop_table('subagent_threads')
