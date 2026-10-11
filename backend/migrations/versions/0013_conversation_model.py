"""per-conversation chat model alias

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL = 用 DEFAULT_MODEL；见 app/llm.py chat_model
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('model')
