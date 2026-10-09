FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1'
COPY services/__init__.py /app/services/__init__.py
COPY services/terminology/ /app/services/terminology/
COPY resources/diagnoses/icd10_cn_national_clinical_v2_2019.xlsx /app/resources/diagnoses/
COPY resources/diagnoses/icd10_cn_covid_addendum_2020.csv /app/resources/diagnoses/
RUN python -m services.terminology.build_catalog \
    /app/resources/diagnoses/icd10_cn_national_clinical_v2_2019.xlsx \
    /app/catalog/diagnoses.sqlite3 \
    /app/resources/diagnoses/icd10_cn_covid_addendum_2020.csv \
    && rm -rf /app/resources

RUN useradd --create-home --uid 10003 smartmed
USER smartmed

EXPOSE 8002
CMD ["uvicorn", "services.terminology.app:app", "--host", "0.0.0.0", "--port", "8002"]
