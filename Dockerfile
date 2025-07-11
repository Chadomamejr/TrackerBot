# ベースイメージをPython 3.11に指定 (元のファイルに合わせる)
FROM python:3.12-slim-bookworm

LABEL maintainer="Your Name <your.email@example.com>"

# 作業ディレクトリを設定
WORKDIR /bot

# aptパッケージの更新、FFmpegのインストール、ロケールの設定、タイムゾーンの設定
# 読み取り専用ファイルシステムのエラー回避のため '-o Acquire::PDiffs=false' を追加
# aptキャッシュの削除は一層で実行し、イメージサイズを最適化
RUN apt-get update -o Acquire::PDiffs=false && \
    apt-get install -y ffmpeg locales && \
    localedef -f UTF-8 -i ja_JP ja_JP.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

# 環境変数を設定（日本語環境とタイムゾーン）
ENV LANG ja_JP.UTF-8
ENV LANGUAGE ja_JP:ja
ENV LC_ALL ja_JP.UTF-8
ENV TZ Asia/Tokyo
ENV TERM xterm

# requirements.txt をコピーしてPythonパッケージをインストール
# pip install の警告抑制 (--root-user-action=ignore) とキャッシュ無効化 (--no-cache-dir) を追加
COPY requirements.txt /bot/
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

# アプリケーションのコードをコピー
COPY . /bot

# ポート開放 (必要であれば変更)
EXPOSE 8080

# アプリケーションの実行コマンド
CMD ["python", "app/main.py"]