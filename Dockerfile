FROM python:3.12-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src/ src/
COPY scripts/ scripts/
COPY data/universe/ data/universe/
COPY data/metadata.db data/metadata.db
COPY configs/ configs/

EXPOSE 8080

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "uvicorn", "indian_quant.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
