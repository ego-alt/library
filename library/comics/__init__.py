"""Comics: follow series, get new issues (through the shared downloads), and
read them. Pages and API live under /comics/."""

from .routes import comics_blueprint


def init_comics(app) -> None:
    from . import models  # noqa: F401  (tables known to migrations)

    app.register_blueprint(comics_blueprint)
