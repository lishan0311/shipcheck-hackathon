FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 ALLOW_DEMO_MODE=false AUTO_PROCESS_INBOX=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY model/ ./model/
RUN python -m model.train
COPY sdoc-hackathon-bundle/ ./sdoc-hackathon-bundle/
COPY run.py ./
COPY --from=frontend /app/frontend/dist/ ./frontend/dist/
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "run.py", "--host", "0.0.0.0"]
