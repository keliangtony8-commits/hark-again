"""v2.20 后台任务借用已连接账户（app/command_credentials.py）：jobs.credentials（逗号分隔的服务商 id）。
每次启动 / 重启现取 Token；NULL = 没借。

Revision ID: 0053
Revises: 0052
"""
from alembic import op
import sqlalchemy as sa

revision = '0053'
down_revision = '0052'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('credentials', sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('credentials')
