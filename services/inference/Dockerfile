FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ARTIFACT_DIR=/artifacts

RUN python -m pip install --no-cache-dir -U pip

# dipendenze inference
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir awscli

# codice
COPY . /app

# entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /artifacts

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
