"""budget alerts: alerts_sent dedupe table + home_cards.target

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/usage.py check_budget：每条提醒一个 key，主键冲突 = 已发过
    op.create_table(
        'alerts_sent',
        sa.Column('key', sa.String(length=96), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table('home_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('home_cards', schema=None) as batch_op:
        batch_op.drop_column('target')
    op.drop_table('alerts_sent')
