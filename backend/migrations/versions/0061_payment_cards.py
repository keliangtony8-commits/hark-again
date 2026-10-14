"""v2.74 钱包：payment_cards（app/wallet.py 规则）。

Revision ID: 0061
Revises: 0060
"""
from alembic import op
import sqlalchemy as sa

revision = '0061'
down_revision = '0060'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payment_cards',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('label', sa.String(60), nullable=False),
        sa.Column('brand', sa.String(16), nullable=False),
        sa.Column('last4', sa.String(4), nullable=False),
        sa.Column('exp_month', sa.Integer(), nullable=False),
        sa.Column('exp_year', sa.Integer(), nullable=False),
        sa.Column('holder', sa.String(80), nullable=False, server_default=''),
        sa.Column('postal_code', sa.String(16), nullable=False, server_default=''),
        sa.Column('ciphertext', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('payment_cards')
