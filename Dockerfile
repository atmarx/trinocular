FROM python:3.13-slim-trixie

# libjxr-tools: JxrDecApp, the only thing that reads the Pro2's color frames.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libjxr-tools \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY trinocular/ trinocular/

# Certs are not baked in — mount them (see certs/README.md).
ENV TRINOCULAR_DATA=/data \
    TRINOCULAR_CERTS=/certs \
    CAMERA_URL=https://10.77.80.1
VOLUME /data
EXPOSE 8796
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8796/healthz')"
CMD ["uvicorn", "trinocular.app:app", "--host", "0.0.0.0", "--port", "8796"]
