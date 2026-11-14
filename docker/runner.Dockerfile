# Runner image for SANDBOX_MODE=docker. Stdlib only: no pip install, nothing from the host leaks in.
# Build: make docker-runner   (context = backend/)
FROM python:3.14-slim
COPY glassbox/__init__.py /opt/glassbox/glassbox/__init__.py
COPY glassbox/runner /opt/glassbox/glassbox/runner
ENV PYTHONPATH=/opt/glassbox PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /work
# The API starts the container with the hardening flags (see sandbox/docker_backend.py).
CMD ["python", "-s", "-P", "-X", "utf8", "-m", "glassbox.runner", "/job/job.json"]
