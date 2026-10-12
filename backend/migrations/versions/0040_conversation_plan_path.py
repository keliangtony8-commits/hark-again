"""conversations.plan_path：计划模式批准的方案存成的工作区文件（app/plan_mode.py plan_file）。
之后每轮系统提示提到它（文件被删 = 不再按它做）。老对话 NULL。

Revision ID: 0040
Revises: 0039
"""
from alembic import op
import sqlalchemy as sa

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('plan_path', sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('conversations') as b:
        b.drop_column('plan_path')
