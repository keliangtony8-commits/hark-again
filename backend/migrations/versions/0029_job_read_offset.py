"""jobs.read_offset + followup_at: job_status 只给新输出；叫醒轮数上限（移植自 deepseek-harness tool-jobs）

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.add_column(sa.Column('read_offset', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('followup_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('followup_at')
        b.drop_column('read_offset')
