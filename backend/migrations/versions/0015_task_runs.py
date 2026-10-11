"""task run history: task_runs + scheduled_tasks.last_status

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/task_runs.py：一次运行一行，每个任务只留最近若干条；task_id 不设外键（删任务时手动清）
    op.create_table(
        'task_runs',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('trigger', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('conversation_id', sa.String(length=32), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_task_runs_task_id', 'task_runs', ['task_id'])
    with op.batch_alter_table('scheduled_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_status', sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('scheduled_tasks', schema=None) as batch_op:
        batch_op.drop_column('last_status')
    op.drop_index('ix_task_runs_task_id', table_name='task_runs')
    op.drop_table('task_runs')
