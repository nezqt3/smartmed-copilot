FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
RUN python -c "import subprocess,sys,tomllib; d=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; subprocess.check_call([sys.executable,'-m','pip','install','setuptools>=68',*d])"
COPY src/ ./src/
RUN pip install --no-deps --no-build-isolation -e .

RUN useradd --create-home --uid 10001 smartmed && mkdir -p /app/data \
    && chown -R smartmed:smartmed /app/data
USER smartmed

EXPOSE 8000
CMD ["uvicorn", "smartmed.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
