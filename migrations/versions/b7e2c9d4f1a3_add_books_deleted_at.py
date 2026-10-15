"""add books deleted_at for soft delete

Revision ID: b7e2c9d4f1a3
Revises: a1b2c3d4e5f6
Create Date: 2026-10-15

"""
from alembic import op
import sqlalchemy as sa


revision = "b7e2c9d4f1a3"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_books_deleted_at", ["deleted_at"], unique=False)


def downgrade():
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.drop_index("ix_books_deleted_at")
        batch_op.drop_column("deleted_at")
