# Static UI behind nginx, proxying /api and /ws to the `api` service. Build context = repository root.
FROM node:24-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY examples ./examples
RUN cd frontend && npm ci
COPY frontend ./frontend
RUN cd frontend && npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/frontend/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
