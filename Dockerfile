FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY runtime.part* /app/pkg/

RUN cat /app/pkg/runtime.part* | base64 -d > /tmp/runtime.tar.xz \
    && tar -xJf /tmp/runtime.tar.xz -C /app \
    && rm -rf /app/pkg /tmp/runtime.tar.xz

COPY apply-staging-patch.py /app/apply-staging-patch.py
RUN python /app/apply-staging-patch.py

COPY tailscale_support.py /app/playzone/backend/app/tailscale_support.py
COPY apply-tailscale-v021.py /app/apply-tailscale-v021.py
RUN python /app/apply-tailscale-v021.py

COPY apply-hotfix-v022.py /app/apply-hotfix-v022.py
RUN python /app/apply-hotfix-v022.py

COPY v023_patch.zlib.b64 /app/v023_patch.zlib.b64
RUN python -c "import base64,zlib,pathlib; p=pathlib.Path('/app/v023_patch.zlib.b64'); pathlib.Path('/app/apply-performance-v023.py').write_bytes(zlib.decompress(base64.b64decode(p.read_text().strip())))" \
    && python /app/apply-performance-v023.py

RUN pip install --no-cache-dir -r /app/playzone/backend/requirements.txt

COPY start-staging.sh /app/start-staging.sh
RUN chmod +x /app/start-staging.sh

ENV PYTHONUNBUFFERED=1 \
    VOLTRA_EMBEDDED=1 \
    VOLTRA_TCP_PORT=10086 \
    VOLTRA_HTTP_PORT=8086

EXPOSE 8080 10086

CMD ["/app/start-staging.sh"]
