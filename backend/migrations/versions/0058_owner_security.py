"""v2.58 owner_security：主人的两步验证（app/two_factor.py 规则）。

Revision ID: 0058
Revises: 0057
"""
from alembic import op
import sqlalchemy as sa

revision = '0058'
down_revision = '0057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'owner_security',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('secret', sa.Text(), nullable=True),
        sa.Column('pending', sa.Text(), nullable=True),
        sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_step', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('recovery', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('owner_security')
