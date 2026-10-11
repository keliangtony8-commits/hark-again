"""memory digest ("what I know about you")

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/memory_digest.py：单行表，id 固定 "me"
    op.create_table(
        'memory_digest',
        sa.Column('id', sa.String(length=16), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('memory_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('memory_digest')
