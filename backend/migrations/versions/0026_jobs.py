"""background jobs (项目沙盒后台任务，见 app/jobs.py)

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('project_id', sa.String(32), nullable=False),
        sa.Column('conversation_id', sa.String(32), nullable=True),
        sa.Column('task_id', sa.String(32), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('timeout', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default='running'),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('followup', sa.String(16), nullable=False, server_default='none'),
        sa.Column('tail', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_jobs_project_id', 'jobs', ['project_id'])
    op.create_index('ix_jobs_conversation_id', 'jobs', ['conversation_id'])
    op.create_index('ix_jobs_state', 'jobs', ['state'])


def downgrade() -> None:
    op.drop_table('jobs')
