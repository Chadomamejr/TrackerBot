# ベースイメージの指定（ここからDockerイメージが作られる）
FROM python:3.13-slim-bookworm

# イメージ作成者の情報（オプション）
LABEL maintainer="Your Name <your.email@example.com>"

# システムパッケージの更新とFFmpegのインストール
# && でコマンドを連結し、aptキャッシュを削除してイメージサイズを小さくする
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定（コンテナ内でコマンドが実行される場所）
WORKDIR /app

# ホスト（あなたのPC）のrequirements.txtをコンテナの/appにコピー
COPY requirements.txt .

# Pythonの依存関係をインストール（キャッシュを使わないことでイメージサイズを抑える）
RUN pip install --no-cache-dir -r requirements.txt

# ホストの現在のディレクトリにある残りのすべてのファイルをコンテナの/appにコピー
COPY . .

# コンテナが起動したときに実行されるコマンド
# ここではPythonスクリプト（main.py）を実行するように設定
CMD ["python", "main.py"]
