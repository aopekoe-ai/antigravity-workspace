FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEPREFIX=/root/.wine
ENV WINEDEBUG=-all
ENV DISPLAY=:99

# 1. 必要なツールのインストール & Wineのセットアップ
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wine64 \
        wine32 \
        wine \
        xvfb \
        wget \
        curl \
        unzip \
        ca-certificates \
        procps && \
    rm -rf /var/lib/apt/lists/*

# Wineのサイレント初期化
RUN xvfb-run -a wineboot --init

# 2. Windows版 Python 3.10 (Embeddable ZIP) の展開
# インストーラー(.exe)を使わず直接展開するため、Wineインストーラーエラーが絶対に起きない
RUN mkdir -p /root/.wine/drive_c/Python310 && \
    wget -q https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip -O /tmp/py.zip && \
    unzip /tmp/py.zip -d /root/.wine/drive_c/Python310 && \
    rm -f /tmp/py.zip && \
    sed -i 's/#import site/import site/' /root/.wine/drive_c/Python310/python310._pth

# 3. get-pip で pip を導入
RUN wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py && \
    xvfb-run -a wine /root/.wine/drive_c/Python310/python.exe /tmp/get-pip.py && \
    rm -f /tmp/get-pip.py

# 4. 依存ライブラリのインストール
RUN xvfb-run -a wine /root/.wine/drive_c/Python310/python.exe -m pip install --no-cache-dir \
        MetaTrader5 \
        pandas \
        requests \
        google-genai \
        pydantic

WORKDIR /app
COPY . /app
RUN chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
