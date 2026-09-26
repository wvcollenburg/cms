"""media focal point

Revision ID: b7e2d4c1a9f3
Revises: a3c1e0f2b9d4
Create Date: 2026-09-26

"""
import sqlalchemy as sa
from alembic import op

revision = 'b7e2d4c1a9f3'
down_revision = 'a3c1e0f2b9d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('media') as batch:
        batch.add_column(sa.Column('focus_x', sa.SmallInteger(), nullable=False, server_default='50'))
        batch.add_column(sa.Column('focus_y', sa.SmallInteger(), nullable=False, server_default='50'))


def downgrade():
    with op.batch_alter_table('media') as batch:
        batch.drop_column('focus_y')
        batch.drop_column('focus_x')
