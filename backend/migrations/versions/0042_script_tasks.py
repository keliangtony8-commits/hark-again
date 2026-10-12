"""定时脚本（v1.84，app/script_tasks.py）：scheduled_tasks.kind / project_id / notify / output_digest，task_runs.job_id。
老任务都是让助手执行的指令：kind=agent、notify=failure，其余 NULL。

Revision ID: 0042
Revises: 0041
"""
from alembic import op
import sqlalchemy as sa

revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('kind', sa.String(16), nullable=False, server_default='agent'))
    op.add_column('scheduled_tasks', sa.Column('project_id', sa.String(32), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('notify', sa.String(16), nullable=False, server_default='failure'))
    op.add_column('scheduled_tasks', sa.Column('output_digest', sa.String(64), nullable=True))
    op.add_column('task_runs', sa.Column('job_id', sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('task_runs') as b:
        b.drop_column('job_id')
    with op.batch_alter_table('scheduled_tasks') as b:
        for col in ('output_digest', 'notify', 'project_id', 'kind'):
            b.drop_column(col)
