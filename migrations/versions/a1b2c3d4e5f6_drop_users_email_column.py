"""drop users email column

Revision ID: a1b2c3d4e5f6
Revises: 717c2541940c
Create Date: 2026-05-15

"""
import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "717c2541940c"
branch_labels = None
depends_on = None


def upgrade():
    # Some databases were created after the column was already gone from the
    # model; only drop it where it exists.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
    if "email" not in columns:
        return
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=120), nullable=True))
