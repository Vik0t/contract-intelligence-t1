# CUDA 12.8 supports both Hopper (H100) and Blackwell (RTX 5090).
ARG RUNTIME_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04
FROM ${RUNTIME_IMAGE} AS backend
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH HF_HOME=/models HOME=/home/contract
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev build-essential libpq-dev ca-certificates \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng libreoffice-writer \
    fonts-dejavu-core fonts-liberation libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
WORKDIR /app
COPY deploy/requirements-server.in /app/deploy/requirements-server.in
COPY deploy/cuda-constraints.in /app/deploy/cuda-constraints.in
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url ${TORCH_INDEX_URL} \
    && pip install --no-cache-dir -r deploy/requirements-server.in -c deploy/cuda-constraints.in \
    && pip check
RUN useradd --create-home --uid 10001 contract \
    && mkdir -p /data/uploads /models /reports && chown -R contract:contract /data /models /reports
COPY --chown=contract:contract backend /app/backend
COPY --chown=contract:contract src /app/src
COPY --chown=contract:contract scripts /app/scripts
USER contract
EXPOSE 8000
CMD ["python", "-m", "scripts.serve"]
