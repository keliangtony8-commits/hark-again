"""conversations.mode / mode_seen：计划模式（app/plan_mode.py）。mode = default | plan（老对话 default）；
mode_seen = 上一轮模型看到的模式，切换后下一轮先告诉模型一句。

Revision ID: 0039
Revises: 0038
"""
from alembic import op
import sqlalchemy as sa

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('mode', sa.String(8), nullable=False, server_default='default'))
    op.add_column('conversations', sa.Column('mode_seen', sa.String(8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('conversations') as b:
        b.drop_column('mode_seen')
        b.drop_column('mode')
