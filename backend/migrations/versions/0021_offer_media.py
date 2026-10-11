"""home offer cards: picture + source link (建议卡配图和原页链接)

Revision ID: 0021
Revises: 0020
"""
from alembic import op
import sqlalchemy as sa


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/home_offers.py：image_url = 卡顶配图；link_url = “来源 · 域名”链接。都只存 http(s)
    with op.batch_alter_table('home_cards') as b:
        b.add_column(sa.Column('image_url', sa.String(1024), nullable=True))
        b.add_column(sa.Column('link_url', sa.String(1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_column('link_url')
        b.drop_column('image_url')
