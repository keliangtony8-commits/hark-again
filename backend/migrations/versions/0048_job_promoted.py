"""前台命令转后台（v2.04，app/jobs.py adopt）：jobs.promoted —— 这个后台任务是前台 run_command 到点没跑完、
没被杀而是转进来的（卡片上标“从前台转入”，给模型的结论里也说明）。

Revision ID: 0048
Revises: 0047
"""
from alembic import op
import sqlalchemy as sa

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('promoted', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('promoted')
