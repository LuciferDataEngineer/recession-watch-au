FROM --platform=linux/amd64 kestra/kestra:latest-lts-slim

USER root
# Install into the system interpreter. The image puts its own virtualenv
# first on PATH, and installing into that environment breaks the server binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN /usr/bin/pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt
WORKDIR /work
