"""message status (stopped replies)

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # done = 正常说完；stopped = 用户中途点了“停止”，内容是半截的
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=16), server_default='done', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('status')
