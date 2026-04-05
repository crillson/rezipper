FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5063 \
    DATA_DIR=/data \
    CONFIG_DIR=/config

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends p7zip-full wget ca-certificates tar \
    && wget -qO /tmp/rarlinux.tar.gz https://www.rarlab.com/rar/rarlinux-x64-701.tar.gz \
    && tar -xzf /tmp/rarlinux.tar.gz -C /tmp \
    && install -m 0755 /tmp/rar/rar /usr/local/bin/rar \
    && install -m 0755 /tmp/rar/unrar /usr/local/bin/unrar \
    && rm -rf /tmp/rar /tmp/rarlinux.tar.gz \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY WHATS_NEW.md /app/WHATS_NEW.md
COPY templates /app/templates
COPY static /app/static

EXPOSE 5063

CMD ["python", "app.py"]