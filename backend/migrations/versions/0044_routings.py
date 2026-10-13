"""自动选模型的账（v1.95，app/router_stats.py）：routings 表每轮一行（Gemini ModelRoutingEvent 的形状），
usage.route = 这次调用所在那一轮被路由到的档位（simple / complex，非自动轮为 NULL）。

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'routings',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('conversation_id', sa.String(32), nullable=True),
        sa.Column('model', sa.String(64), nullable=False),
        sa.Column('complexity', sa.String(16), nullable=False, server_default=''),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_routings_created_at', 'routings', ['created_at'])
    op.add_column('usage', sa.Column('route', sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('usage') as b:
        b.drop_column('route')
    op.drop_index('ix_routings_created_at', 'routings')
    op.drop_table('routings')
