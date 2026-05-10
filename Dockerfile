# syntax=docker/dockerfile:1
FROM python:3.10-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
CMD ["uv", "run", "gunicorn", "app:create_app()", "--bind", "0.0.0.0:8002", "--workers", "3", "--threads", "8", "--timeout", "120", "--worker-class", "gthread"]
