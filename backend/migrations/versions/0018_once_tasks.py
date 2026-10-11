"""one-shot scheduled tasks (run_at)

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/schedule.py：cron 与 run_at 二选一，一次性任务 cron 为空串
    with op.batch_alter_table('scheduled_tasks') as b:
        b.add_column(sa.Column('run_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_tasks WHERE run_at IS NOT NULL")
    with op.batch_alter_table('scheduled_tasks') as b:
        b.drop_column('run_at')
