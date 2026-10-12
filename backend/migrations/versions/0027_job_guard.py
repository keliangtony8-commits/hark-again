"""job guard: idle_timeout + stop_reason（后台任务护栏：卡住/输出过大自动停，见 app/jobs.py）

Revision ID: 0027
Revises: 0026
"""
from alembic import op
import sqlalchemy as sa

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.add_column(sa.Column('idle_timeout', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('stop_reason', sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.drop_column('stop_reason')
        b.drop_column('idle_timeout')
