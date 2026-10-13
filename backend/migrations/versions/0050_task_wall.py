"""v2.15 任务碰壁（app/task_wall.py）：scheduled_tasks.wall / wall_reason / wall_at，task_runs.wall。
老任务都没碰壁（NULL），老运行也没有。

Revision ID: 0050
Revises: 0049
"""
from alembic import op
import sqlalchemy as sa

revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('wall', sa.String(length=80), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('wall_reason', sa.String(length=300), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('wall_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('task_runs', sa.Column('wall', sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('task_runs') as b:
        b.drop_column('wall')
    with op.batch_alter_table('scheduled_tasks') as b:
        for col in ('wall_at', 'wall_reason', 'wall'):
            b.drop_column(col)
