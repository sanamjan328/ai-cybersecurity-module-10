FROM python:3.12-slim@sha256:64f02903d2fa7d70adda248450c905550bd468829179cf9fa20d1a168af1d0b3

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY vulnerable_archive/ ./vulnerable_archive/

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -e .

# Create directory for SQLite database if it doesn't exist
RUN mkdir -p /app/vulnerable_archive

# Set working directory to Django project
WORKDIR /app/vulnerable_archive

# Expose port 8000
EXPOSE 8000

# Run Django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
