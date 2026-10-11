"""task fail streak + auto pause (连续失败计数与自动暂停：scheduled_tasks.fail_streak / paused_reason)

Revision ID: 0024
Revises: 0023
"""
from alembic import op
import sqlalchemy as sa


revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/task_runs.py：连续失败 PAUSE_AFTER 次的重复任务自动暂停；老任务上次失败的从 1 算起
    with op.batch_alter_table('scheduled_tasks') as b:
        b.add_column(sa.Column('fail_streak', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('paused_reason', sa.String(16), nullable=True))
    op.execute("UPDATE scheduled_tasks SET fail_streak = 1 WHERE last_status = 'error'")


def downgrade() -> None:
    with op.batch_alter_table('scheduled_tasks') as b:
        b.drop_column('paused_reason')
        b.drop_column('fail_streak')
