FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements-core.txt requirements-ml.txt ./
ARG INSTALL_ML=false
RUN pip install --no-cache-dir -r requirements-core.txt \
    && if [ "$INSTALL_ML" = "true" ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

COPY app ./app
ENV PICARD_DATA_DIR=/data
ENV DATABASE_URL=sqlite:////data/picard.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
