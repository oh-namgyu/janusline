FROM python:3.14-slim

# HOST=0.0.0.0 makes the app reachable from outside the container's own
# namespace. The bind guard in core/auth.py refuses a non-loopback bind without
# AUTH_TOKEN, so the container exits 1 unless you pass one — see README.md.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=6181 \
    JANUSLINE_DATA=/app/data

WORKDIR /app

# Runtime dependencies only; requirements-dev.txt is never installed here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY core ./core
COPY static ./static

# Non-root. /app/data is the writable volume mount point.
RUN useradd --create-home --uid 10001 janusline \
    && mkdir -p /app/data \
    && chown -R janusline:janusline /app
USER janusline

EXPOSE 6181

# Single worker by design: brief writes are serialised with in-process locks, so
# a multi-worker server (gunicorn, uwsgi) would break the storage contract.
CMD ["python", "app.py"]
