"""jobs 常驻任务（v1.80，app/job_restart.py）：keep_alive / restarts / crash_streak / restart_at / run_started_at。
老任务都是普通后台任务：keep_alive=false，计数 0，两个时间 NULL。

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa

revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('keep_alive', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('jobs', sa.Column('restarts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('crash_streak', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('restart_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('run_started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        for col in ('run_started_at', 'restart_at', 'crash_streak', 'restarts', 'keep_alive'):
            b.drop_column(col)
