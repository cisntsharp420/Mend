ARG IMAGE_REGISTRY=mirror.gcr.io/library
FROM ${IMAGE_REGISTRY}/python:3.12-alpine

WORKDIR /app
COPY requirements.txt .
COPY wheels/ /wheels/
# Use pre-downloaded wheels when present (offline/proxied builds), otherwise PyPI.
RUN if ls /wheels/*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi && rm -rf /wheels

COPY *.py ./
COPY tools/ ./tools/
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
