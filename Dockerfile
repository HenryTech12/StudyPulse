# One container: builds the React app and serves it from FastAPI.
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
ENV UPLOAD_DIR=/data/uploads DATABASE_URL=sqlite:////data/studypulse.db
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
