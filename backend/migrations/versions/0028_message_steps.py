"""message steps: 活动时间线（每条回复的工具步骤，见 app/activity.py）

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('messages') as b:
        b.add_column(sa.Column('steps', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('messages') as b:
        b.drop_column('steps')
