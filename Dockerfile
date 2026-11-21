FROM kestra/kestra:latest-slim

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt
WORKDIR /work
ENTRYPOINT ["/app/kestra"]
CMD ["server", "local"]
