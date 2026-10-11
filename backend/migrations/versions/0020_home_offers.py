"""home offer cards (智能体放到 Home 的“我可以帮你做”建议)

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/home_offers.py：action_label = 主按钮上的字；origin = 谁放的卡（agent = 智能体提议；空 = 系统提醒/接口）
    with op.batch_alter_table('home_cards') as b:
        b.add_column(sa.Column('action_label', sa.String(24), nullable=True))
        b.add_column(sa.Column('origin', sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_column('origin')
        b.drop_column('action_label')
