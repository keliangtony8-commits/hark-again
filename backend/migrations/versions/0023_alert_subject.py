"""system alerts keyed by subject (系统提醒按主体收起/顶替：home_cards.alert_subject)

Revision ID: 0023
Revises: 0022
"""
from alembic import op
import sqlalchemy as sa


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 见 app/system_alerts.py：subject = 出事的那个东西；老的系统提醒按去处补上主体
    with op.batch_alter_table('home_cards') as b:
        b.add_column(sa.Column('alert_subject', sa.String(96), nullable=True))
        b.create_index('ix_home_cards_alert_subject', ['alert_subject'])
    sys = "kind = 'action' AND origin IS NULL"
    op.execute(f"UPDATE home_cards SET alert_subject = 'task:' || task_id WHERE {sys} AND task_id IS NOT NULL")
    op.execute(f"UPDATE home_cards SET alert_subject = 'budget' WHERE {sys} AND target = 'usage' AND task_id IS NULL")
    # v0.95 的连接失效卡不知道是哪个账号：只此一版，标成 connector:legacy，用户手动收起
    op.execute(f"UPDATE home_cards SET alert_subject = 'connector:legacy' WHERE {sys} AND target = 'connectors'")


def downgrade() -> None:
    with op.batch_alter_table('home_cards') as b:
        b.drop_index('ix_home_cards_alert_subject')
        b.drop_column('alert_subject')
