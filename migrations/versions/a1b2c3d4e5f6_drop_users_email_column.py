"""drop users email column

Revision ID: a1b2c3d4e5f6
Revises: 717c2541940c
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "717c2541940c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=120), nullable=True))
