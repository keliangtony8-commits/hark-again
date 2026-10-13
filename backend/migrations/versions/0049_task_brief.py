"""v2.13 任务的“做法 + 观察”（app/task_brief.py）：scheduled_tasks.runbook / note / skip_at，task_runs.silent_reason。
老任务都没有做法和观察（NULL）、没有跳过；老运行都“说过话”（silent_reason NULL）。

Revision ID: 0049
Revises: 0048
"""
from alembic import op
import sqlalchemy as sa

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('runbook', sa.Text(), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('note', sa.Text(), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('skip_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('task_runs', sa.Column('silent_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('task_runs') as b:
        b.drop_column('silent_reason')
    with op.batch_alter_table('scheduled_tasks') as b:
        for col in ('skip_at', 'note', 'runbook'):
            b.drop_column(col)
