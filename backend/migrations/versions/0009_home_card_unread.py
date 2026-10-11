"""home card unread flag (inbox badge)

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 升级前已有的卡一律算已读，免得一升级就冒出一堆角标
    with op.batch_alter_table('home_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unread', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('home_cards', schema=None) as batch_op:
        batch_op.drop_column('unread')
