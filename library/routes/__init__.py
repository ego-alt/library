from .auth import auth as auth_blueprint
from .index import index_blueprint
from .metadata import metadata_blueprint
from .reader import read_blueprint
from .upload import upload_blueprint

__all__ = [
    "auth_blueprint",
    "index_blueprint",
    "metadata_blueprint",
    "read_blueprint",
    "upload_blueprint",
]
