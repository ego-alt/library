"""add comics: series, issues, downloads, reading progress, settings

Revision ID: c4d8e1f2a9b6
Revises: b7e2c9d4f1a3
Create Date: 2026-10-21

"""
import sqlalchemy as sa
from alembic import op

revision = "c4d8e1f2a9b6"
down_revision = "b7e2c9d4f1a3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comic_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("cv_id", sa.Integer()),
        sa.Column("metron_id", sa.Integer()),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_year", sa.Integer()),
        sa.Column("publisher", sa.String(120)),
        sa.Column("volume", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.Column("cover_url", sa.String(500)),
        sa.Column("issue_count", sa.Integer()),
        sa.Column("monitor", sa.String(10), nullable=False),
        sa.Column("folder", sa.String(400)),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime()),
        sa.UniqueConstraint("provider", "provider_id", name="uq_comic_series_provider"),
    )
    op.create_table(
        "comic_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("comic_series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.String(32)),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("sort_number", sa.Float(), nullable=False),
        sa.Column("title", sa.String(300)),
        sa.Column("cover_date", sa.Date()),
        sa.Column("store_date", sa.Date()),
        sa.Column("cover_url", sa.String(500)),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("filename", sa.String(500), unique=True),
        sa.Column("file_size", sa.Integer()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("series_id", "provider_id", name="uq_comic_issue_provider"),
    )
    op.create_index("ix_comic_issues_series_id", "comic_issues", ["series_id"])
    op.create_index("ix_comic_issues_status", "comic_issues", ["status"])
    op.create_table(
        "comic_downloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("comic_issues.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("indexer", sa.String(100)),
        sa.Column("protocol", sa.String(10)),
        sa.Column("url", sa.Text()),
        sa.Column("size", sa.BigInteger()),
        sa.Column("client", sa.String(20)),
        sa.Column("client_ref", sa.String(200)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("progress", sa.Float()),
        sa.Column("error", sa.Text()),
        sa.Column("path", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_comic_downloads_issue_id", "comic_downloads", ["issue_id"])
    op.create_index("ix_comic_downloads_status", "comic_downloads", ["status"])
    op.create_table(
        "comic_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("comic_issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "issue_id", name="uq_comic_progress_user_issue"),
    )
    op.create_table(
        "comic_settings",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("comic_settings")
    op.drop_table("comic_progress")
    op.drop_index("ix_comic_downloads_status", "comic_downloads")
    op.drop_index("ix_comic_downloads_issue_id", "comic_downloads")
    op.drop_table("comic_downloads")
    op.drop_index("ix_comic_issues_status", "comic_issues")
    op.drop_index("ix_comic_issues_series_id", "comic_issues")
    op.drop_table("comic_issues")
    op.drop_table("comic_series")
