"""v2.18 后台任务改了哪些文件（app/job_changes.py）：jobs.changes（JSON 文本）。老任务没有（NULL = 卡上没有改动区）。

Revision ID: 0052
Revises: 0051
"""
from alembic import op
import sqlalchemy as sa

revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('changes', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('changes')
