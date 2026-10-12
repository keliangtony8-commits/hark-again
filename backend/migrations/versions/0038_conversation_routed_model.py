"""conversations.routed_model：选了“自动”（app/model_router.py）时上一轮实际用的别名——客户端显示“自动 · 快速”，
“继续”这类接话沿用它。老对话为空。

Revision ID: 0038
Revises: 0037
"""
from alembic import op
import sqlalchemy as sa

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('routed_model', sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('conversations') as b:
        b.drop_column('routed_model')
