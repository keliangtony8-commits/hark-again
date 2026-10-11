"""model usage records (tokens + cost per call)

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 一次模型调用一行；见 app/usage.py。conversation_id 故意不设外键（删对话不删账）
    op.create_table(
        'usage',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('conversation_id', sa.String(length=32), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('cost', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_usage_conversation_id', 'usage', ['conversation_id'])
    op.create_index('ix_usage_created_at', 'usage', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_usage_created_at', table_name='usage')
    op.drop_index('ix_usage_conversation_id', table_name='usage')
    op.drop_table('usage')
