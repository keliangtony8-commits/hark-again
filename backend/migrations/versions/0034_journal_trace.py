"""turn_journals.trace: 崩溃检查点也存工具轨迹（app/turn_journal.py；恢复成 interrupted 消息时带上，下一轮照样重放）

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('turn_journals', sa.Column('trace', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('turn_journals') as b:
        b.drop_column('trace')
