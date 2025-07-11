FROM python:3.13-slim-bookworm

LABEL maintainer="Your Name <your.email@example.com>"

# apt-get update に -o Acquire::PDiffs=false を追加して、読み取り専用ファイルシステムのエラーを回避
RUN apt-get update -o Acquire::PDiffs=false && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# pip install の警告を抑制するオプションも追加（任意）
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

COPY . .

CMD ["python", "main.py"]
