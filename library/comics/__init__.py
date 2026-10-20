"""Comics: follow series, download new issues, and read them (a Mylar-style
manager inside Shelves). Pages and API live under /comics/."""

from .routes import comics_blueprint


def init_comics(app) -> None:
    from . import jobs, models  # noqa: F401  (models: tables known to migrations)

    app.register_blueprint(comics_blueprint)

    # The worker starts with the first request, so `flask db upgrade` and
    # other commands never run it.
    @app.before_request
    def _start_comics_worker():
        jobs.start(app)
