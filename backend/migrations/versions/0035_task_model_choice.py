"""scheduled_tasks.model + reasoning：定时任务自己的模型和思考强度（null = 默认；worker 开对话时抄过去，见 app/task_store.py choice）

Revision ID: 0035
Revises: 0034
"""
from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('model', sa.String(64), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('reasoning', sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('scheduled_tasks') as b:
        b.drop_column('reasoning')
        b.drop_column('model')
