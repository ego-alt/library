# syntax=docker/dockerfile:1
FROM python:3.10-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# bsdtar (libarchive) unpacks CBR and CB7 comics, RAR5 included.
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy project metadata first to leverage Docker cache
COPY pyproject.toml uv.lock /app/

# Install Python dependencies
RUN uv sync --frozen --no-dev

# Copy the rest of the project files
COPY . /app/

# Set production environment variables
ENV FLASK_ENV=production
ENV FLASK_APP=app.py

# Expose the port that the app will run on
EXPOSE 8002

# Run the Flask application using Gunicorn with the correct module reference.
# This tells Gunicorn to call the create_app() factory in app.py.
# Straight from the virtualenv: `uv run` would install the dev tools on every start.
# Two workers: each holds ~150 MB, and the Pi shares 1.8 GB with five other apps.
CMD [".venv/bin/gunicorn", "app:create_app()", "--bind", "0.0.0.0:8002", "--workers", "2", "--threads", "8", "--timeout", "120", "--worker-class", "gthread"]
