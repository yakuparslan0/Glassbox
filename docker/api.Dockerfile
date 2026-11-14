# API image. The API never runs user code itself: with SANDBOX_MODE=docker it starts the `glassbox-runner` image
# through the Docker socket. NOT verified on the development machine (no Docker there): treat it as a starting point.
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend /app/backend
RUN pip install --no-cache-dir /app/backend
ENV SANDBOX_MODE=docker GLASSBOX_ALLOW_REMOTE=true GLASSBOX_HOST=0.0.0.0 GLASSBOX_PORT=8000
EXPOSE 8000
CMD ["glassbox", "serve"]
