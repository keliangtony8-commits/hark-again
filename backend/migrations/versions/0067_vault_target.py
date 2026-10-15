"""v2.96 “我 → 连接的账号”一页：保险箱页并进连接的账号页，卡片去处 vault 不再存在。
已有主页卡 target='vault' 改成 'connectors'（同一页）。单向数据清理：downgrade 不还原——旧服务端也认识 connectors。

Revision ID: 0067
Revises: 0066
"""
from alembic import op

revision = '0067'
down_revision = '0066'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE home_cards SET target = 'connectors' WHERE target = 'vault'")


def downgrade() -> None:
    pass
