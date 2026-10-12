"""后台任务内存上限与峰值（v1.92，app/job_memory.py）：jobs.memory_max（字节，NULL = 不单独设限，只受整台沙盒上限约束）、
jobs.memory_peak（worker 采样看到的最高 PSS，字节）。

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('memory_max', sa.BigInteger(), nullable=True))
    op.add_column('jobs', sa.Column('memory_peak', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('memory_peak')
        b.drop_column('memory_max')
