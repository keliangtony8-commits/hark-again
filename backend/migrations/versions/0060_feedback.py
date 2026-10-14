"""v2.64 feedback：回复评价 + 问题报告（app/feedback.py 规则）+ messages.feedback。

Revision ID: 0060
Revises: 0059
"""
from alembic import op
import sqlalchemy as sa

revision = '0060'
down_revision = '0059'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('message_id', sa.String(32), nullable=True),
        sa.Column('conversation_id', sa.String(32), nullable=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_feedback_message_id', 'feedback', ['message_id'])
    with op.batch_alter_table('messages') as b:
        b.add_column(sa.Column('feedback', sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('messages') as b:
        b.drop_column('feedback')
    op.drop_index('ix_feedback_message_id', 'feedback')
    op.drop_table('feedback')
