# syntax=docker/dockerfile:1
# CUDA 12.8 supports both Hopper (H100) and Blackwell (RTX 5090).
# The official cu128 Torch wheel supplies cuDNN/cuBLAS and CUDA libraries.
# Keep the base image minimal instead of shipping a second copy of those libs.
ARG RUNTIME_IMAGE=nvidia/cuda:12.8.1-base-ubuntu24.04
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
ENV PIP_DEFAULT_TIMEOUT=60 PIP_RESUME_RETRIES=5 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/home/contract/.cache/pip \
    pip install pip==25.2 --index-url https://pypi.org/simple \
    && pip download --no-deps --dest /tmp/torch-wheels \
        torch==2.7.1 torchvision==0.22.1 --index-url ${TORCH_INDEX_URL} \
    && pip install /tmp/torch-wheels/*.whl --index-url https://pypi.org/simple \
    && rm -rf /tmp/torch-wheels \
    && pip install -r deploy/requirements-server.in -c deploy/cuda-constraints.in --index-url https://pypi.org/simple \
    && pip check
RUN useradd --create-home --uid 10001 contract \
    && mkdir -p /data/uploads /models /reports && chown -R contract:contract /home/contract /data /models /reports
COPY --chown=contract:contract backend /app/backend
COPY --chown=contract:contract src /app/src
COPY --chown=contract:contract scripts /app/scripts
USER contract
EXPOSE 8000
CMD ["python", "-m", "scripts.serve"]
