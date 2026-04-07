FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies required to compile packages like lxml, spacy, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first so this layer is cached and only rebuilt when
# requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code (fast layer, no heavy installs).
COPY . .

# Create runtime directories the application may need.
RUN mkdir -p data templates

EXPOSE 8080

CMD ["python", "run_all.py"]
