"""home card snooze (稍后提醒)

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/card_snooze.py：非空 = 收起到这个时刻，worker 到点叫醒
    with op.batch_alter_table('home_cards') as b:
        b.add_column(sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True))
        b.create_index('ix_home_cards_snoozed_until', ['snoozed_until'])


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_index('ix_home_cards_snoozed_until')
        b.drop_column('snoozed_until')
