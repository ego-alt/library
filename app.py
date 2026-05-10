"""Top-level entrypoint kept for `flask run` and gunicorn discovery.

The actual application lives in the `library` package; this module just
re-exports the factory and provides a CLI-friendly `app` instance.
"""

from library import create_app

app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8002)
