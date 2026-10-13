"""v2.55 panel_entries：记录面板里用户报的每一笔（app/panel_log.py 规则）。

Revision ID: 0057
Revises: 0056
"""
from alembic import op
import sqlalchemy as sa

revision = '0057'
down_revision = '0056'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'panel_entries',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('task_id', sa.String(32), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('text', sa.String(200), nullable=False),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(16), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_panel_entries_task_id', 'panel_entries', ['task_id'])
    op.create_index('ix_panel_entries_at', 'panel_entries', ['at'])


def downgrade() -> None:
    op.drop_index('ix_panel_entries_at', 'panel_entries')
    op.drop_index('ix_panel_entries_task_id', 'panel_entries')
    op.drop_table('panel_entries')
