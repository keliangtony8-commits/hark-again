"""project brief (living doc per project)

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/project_brief.py
    with op.batch_alter_table('projects') as b:
        b.add_column(sa.Column('brief', sa.Text(), nullable=False, server_default=''))
        b.add_column(sa.Column('brief_by', sa.String(length=16), nullable=True))
        b.add_column(sa.Column('brief_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as b:
        b.drop_column('brief_updated_at')
        b.drop_column('brief_by')
        b.drop_column('brief')
