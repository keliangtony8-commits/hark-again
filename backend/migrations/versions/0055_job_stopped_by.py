"""v2.25 jobs.stopped_by：取消是谁做的（user / agent / guard）。用户停的不叫醒助手，卡片和通知写明。

Revision ID: 0055
Revises: 0054
"""
from alembic import op
import sqlalchemy as sa

revision = '0055'
down_revision = '0054'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('stopped_by', sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'stopped_by')
