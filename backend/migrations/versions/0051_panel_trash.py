"""v2.17 移除的面板可找回（app/panel_trash.py）：home_cards.removed_at / revive_spec。
老卡都不是“移除的面板”（NULL）；v2.17 之前删掉的面板已经连卡删了，找不回。

Revision ID: 0051
Revises: 0050
"""
from alembic import op
import sqlalchemy as sa

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('home_cards', sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('home_cards', sa.Column('revive_spec', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_column('revive_spec')
        b.drop_column('removed_at')
