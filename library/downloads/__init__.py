"""Getting books and comics: indexers, download clients, one queue and one
background worker for both kinds (see pipeline.py), and the Get and Downloads
pages."""


def init_downloads(app) -> None:
    from ..books import getting as book_getting
    from ..books import (
        models as book_models,  # noqa: F401  (tables known to migrations)
    )
    from ..comics import downloads as comic_downloads
    from . import jobs, models, pipeline  # noqa: F401
    from .routes import downloads_blueprint, is_admin, waiting_count

    pipeline.register(comic_downloads.kind)
    pipeline.register(book_getting.kind)
    app.register_blueprint(downloads_blueprint)

    @app.context_processor
    def _nav():
        """What the nav needs on every page: whether to show Get and
        Downloads, and the count on Downloads."""
        admin = is_admin()
        return {"is_admin": admin, "downloads_count": waiting_count() if admin else 0}

    # The worker starts with the first request, so `flask db upgrade` and
    # other commands never run it.
    @app.before_request
    def _start_download_worker():
        jobs.start(app)
