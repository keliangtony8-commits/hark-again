"""conversations.title_source：标题从哪来（app/conversation_title.py）。first = 第一句话截取（第一轮后自动换成模型起的短标题）/
auto / user / fixed。已有对话一律 fixed：老对话不会被突然改名。

Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('title_source', sa.String(8), nullable=False, server_default='fixed'))


def downgrade() -> None:
    with op.batch_alter_table('conversations') as b:
        b.drop_column('title_source')
