"""app_settings + host_rules: 服务器主机模式开关与“以后都允许”的命令前缀（思路移植自 Codex execpolicy）

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'host_rules',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('prefix', sa.JSON(), nullable=False),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('host_rules')
    op.drop_table('app_settings')
