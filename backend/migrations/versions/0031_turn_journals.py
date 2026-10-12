"""turn_journals: 一轮回答进行中的检查点，崩溃后恢复成 interrupted 消息（思路移植自 deepseek-harness session/repair.ts）

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'turn_journals',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('conversation_id', sa.String(32), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.String(32), nullable=True),
        sa.Column('owner', sa.String(48), nullable=False),
        sa.Column('blocks', sa.JSON(), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('beat_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_turn_journals_conversation_id', 'turn_journals', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_turn_journals_conversation_id', 'turn_journals')
    op.drop_table('turn_journals')
