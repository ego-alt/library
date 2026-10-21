from .auth import auth as auth_blueprint
from .index import index_blueprint
from .metadata import metadata_blueprint
from .pwa import pwa_blueprint
from .reader import read_blueprint
from .settings import settings_blueprint
from .upload import upload_blueprint

__all__ = [
    "auth_blueprint",
    "index_blueprint",
    "metadata_blueprint",
    "pwa_blueprint",
    "read_blueprint",
    "settings_blueprint",
    "upload_blueprint",
]
