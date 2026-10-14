"""v2.61 login_sessions：登录设备（app/login_sessions.py 规则）+ owner_security.sessions_cutoff。

Revision ID: 0059
Revises: 0058
"""
from alembic import op
import sqlalchemy as sa

revision = '0059'
down_revision = '0058'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'login_sessions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False, server_default='other'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table('owner_security') as b:
        b.add_column(sa.Column('sessions_cutoff', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('owner_security') as b:
        b.drop_column('sessions_cutoff')
    op.drop_table('login_sessions')
