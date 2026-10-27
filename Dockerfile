FROM python:3.13-slim

# Run as a non-root user (required by PicoPaaS). Directories the app writes to
# are created up front and owned by that user; creating them here (rather than
# running chown -R over /app later) avoids duplicating large layers.
RUN mkdir -p /app/output /app/models /app/.cache/numba \
    && chown -R 10001:10001 /app

WORKDIR /app

# Install dependencies first so Docker can cache this layer independently
# of application code changes. All dependencies ship manylinux wheels, so no
# compiler toolchain is needed in the image.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

USER 10001

# numba (used by pymatting/rembg) must cache compiled functions somewhere
# writable; site-packages is root-owned, so use an app-owned directory.
ENV NUMBA_CACHE_DIR=/app/.cache/numba

# Pre-download the rembg U2Net model into the image so the first request
# doesn't stall while the container fetches ~170 MB at runtime.
# U2NET_HOME is set to a stable app-owned path rather than ~/.u2net so the
# model works correctly regardless of which user the container runs as.
ENV U2NET_HOME=/app/models
RUN python -c "from rembg.sessions.u2net import U2netSession; U2netSession.download_models()"

COPY --chown=10001:10001 . /app

EXPOSE 8000
# Allow configurable worker count via UVICORN_WORKERS (default 2).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
