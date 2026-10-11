"""conversation rolling summary (context compaction)

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # summary 概括开头到 summary_upto（含）的消息；见 app/agent/context.py
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('summary', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('summary_upto', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('summary_upto')
        batch_op.drop_column('summary')
