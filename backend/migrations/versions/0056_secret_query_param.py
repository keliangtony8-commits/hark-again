"""v2.52 secrets.query_param：API Key 放网址参数（?appid=）的服务（app/api_keys.py 规则）。

Revision ID: 0056
Revises: 0055
"""
from alembic import op
import sqlalchemy as sa

revision = '0056'
down_revision = '0055'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('secrets', sa.Column('query_param', sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column('secrets', 'query_param')
