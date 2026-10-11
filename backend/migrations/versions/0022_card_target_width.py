"""home card target holds name:id (卡片去处可带对象 id，如 project:<id>)

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/card_targets.py：target = 名字 或 名字:id；32 位 id 加前缀超过原来的 32 字
    with op.batch_alter_table('home_cards') as b:
        b.alter_column('target', existing_type=sa.String(32), type_=sa.String(64), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.alter_column('target', existing_type=sa.String(64), type_=sa.String(32), existing_nullable=True)
