"""后台任务的磁盘账（v1.96，app/job_disk.py）：jobs.disk（JSON 文本，结算时数一次：日志大小、运行期间工作区新写或改过的文件、
最大的几组、同时段任务数；NULL = 老任务 / 没数成）。

Revision ID: 0045
Revises: 0044
"""
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('disk', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('disk')
