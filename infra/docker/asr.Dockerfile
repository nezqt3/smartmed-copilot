FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir torch==2.5.1 torchaudio==2.5.1
COPY services/asr/requirements.txt /app/requirements-asr.txt
RUN pip install --no-cache-dir -r /app/requirements-asr.txt
COPY services/ /app/services/

RUN useradd --create-home --uid 10002 smartmed && mkdir -p /models \
    && chown -R smartmed:smartmed /models
USER smartmed

EXPOSE 8001
CMD ["uvicorn", "services.asr.app:app", "--host", "0.0.0.0", "--port", "8001"]
