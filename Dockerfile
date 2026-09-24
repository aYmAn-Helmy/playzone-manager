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

RUN pip install --no-cache-dir -r /app/playzone/backend/requirements.txt

COPY start-staging.sh /app/start-staging.sh
RUN chmod +x /app/start-staging.sh

ENV PYTHONUNBUFFERED=1
CMD ["/app/start-staging.sh"]
