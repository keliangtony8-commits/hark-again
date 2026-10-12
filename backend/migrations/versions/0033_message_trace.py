"""messages.trace: 回复的工具轨迹（app/agent/tool_trace.py；下一轮重放给模型，不上协议）

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('trace', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('messages') as b:
        b.drop_column('trace')
