"""usage.cached_tokens：输入里命中提示缓存的部分（app/prompt_cache.py cached_of；用量页显示命中率，命中价另算）

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('usage', sa.Column('cached_tokens', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('usage') as b:
        b.drop_column('cached_tokens')
