# ============================================================
# Personal Books - DOWNLOADER (URL -> PDF -> repo)
# ------------------------------------------------------------
# v2: production-ready.
#     - проверка Content-Type и magic bytes (%PDF)
#     - прогресс скачивания для больших файлов
#     - логи с timestamp
#     - единый стиль с personal_audio.py
# ------------------------------------------------------------
# Требования: pip install requests
# ============================================================

import os
import re
import sys
import html
import requests
from datetime import datetime, timezone
from pathlib import Path

# --- Пути ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PERSONAL_DIR = REPO_ROOT / "personal_books"
PERSONAL_DIR.mkdir(parents=True, exist_ok=True)

# --- Вход ---
URL = (os.getenv("BOOK_URL") or "").strip()
TITLE = (os.getenv("BOOK_TITLE") or "book").strip()

# --- Telegram ---
BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
).strip()
CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or ""
).strip()

# --- Лимиты ---
# GitHub repo hard limit per file = 100 MB
GITHUB_HARD_LIMIT_MB = 100
CHUNK_SIZE = 65536  # 64 KB


# ============================================================
# LOG
# ============================================================
def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print("[" + ts + "] " + str(msg), flush=True)


# ============================================================
# TELEGRAM
# ============================================================
def notify(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("no telegram")
        return False
    try:
        url = "https://api.telegram.org/bot"
        url += BOT_TOKEN + "/sendMessage"
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return r.status_code == 200
    except Exception as e:
        log("tg: " + str(e))
        return False


# ============================================================
# HELPERS
# ============================================================
def safe_filename(title):
    """Нормальное имя файла из заголовка."""
    name = title.lower()
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_-")
    return name[:80] or "document"


def is_pdf_file(path):
    """Проверка magic bytes — начинается ли файл с %PDF."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head == b"%PDF"
    except Exception:
        return False


# ============================================================
# DOWNLOAD
# ============================================================
def download_pdf(url, dest):
    """
    Скачивает PDF с прогрессом.
    Возвращает (ok, size_mb, error_msg).
    """
    try:
        r = requests.get(
            url,
            timeout=300,
            stream=True,
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 PersonalBooks/1.0",
            },
        )
        r.raise_for_status()

        # Проверка Content-Type
        ctype = r.headers.get("Content-Type", "").lower()
        if "pdf" not in ctype and "octet-stream" not in ctype:
            log("unexpected Content-Type: " + ctype)

        total_bytes = 0
        logged_at = 0
        last_log_mb = 0

        with open(dest, "wb") as f:
            for chunk in r.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                total_bytes += len(chunk)

                # Логируем каждые 5 МБ
                cur_mb = total_bytes / 1024 / 1024
                if cur_mb - last_log_mb >= 5:
                    log("  ..." + format(cur_mb, ".1f") + " MB")
                    last_log_mb = cur_mb

                # Защита от огромных файлов
                if cur_mb > GITHUB_HARD_LIMIT_MB + 5:
                    f.close()
                    dest.unlink(missing_ok=True)
                    return (
                        False,
                        0,
                        "too_big",
                    )

        size_mb = total_bytes / 1024 / 1024
        return True, size_mb, None

    except requests.exceptions.Timeout:
        return False, 0, "timeout"
    except requests.exceptions.HTTPError as e:
        return False, 0, "http " + str(e)[:100]
    except Exception as e:
        return False, 0, str(e)[:150]


# ============================================================
# MAIN
# ============================================================
def main():
    # --- Валидация входа ---
    if not URL:
        log("ERR: BOOK_URL not set")
        notify("No URL provided")
        sys.exit(1)

    if not URL.startswith("http"):
        log("ERR: invalid URL")
        notify("Invalid URL")
        sys.exit(1)

    log("=" * 50)
    log("title: " + TITLE[:100])
    log("url:   " + URL[:150])
    log("=" * 50)

    # --- Файл ---
    filename = safe_filename(TITLE) + ".pdf"
    dest = PERSONAL_DIR / filename

    # --- Уже есть ---
    if dest.exists():
        size_mb = dest.stat().st_size / 1024 / 1024
        log("already exists: " + filename)
        notify(
            "Already exists\n\n"
            + html.escape(TITLE[:150])
            + "\n\n" + format(size_mb, ".1f") + " MB"
        )
        return

    # --- Скачивание ---
    log("downloading...")
    ok, size_mb, error = download_pdf(URL, dest)

    if not ok:
        # Уборка
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass

        log("failed: " + str(error))

        if error == "too_big":
            notify(
                "File > 100 MB\n\n"
                + html.escape(TITLE[:150])
                + "\n\nDownload manually:\n" + URL
            )
        elif error == "timeout":
            notify(
                "Timeout\n\n"
                + html.escape(TITLE[:150])
            )
        else:
            notify(
                "Download failed\n\n"
                + html.escape(TITLE[:150])
                + "\n\n<code>" + str(error)[:150] + "</code>"
            )
        sys.exit(1)

    # --- Проверка что это PDF ---
    if not is_pdf_file(dest):
        log("WARNING: not a PDF file (magic bytes)")
        # Может быть HTML страница с ошибкой
        try:
            with open(dest, "rb") as f:
                head = f.read(200)
            log("head: " + str(head[:100]))
        except Exception:
            pass

        dest.unlink(missing_ok=True)
        notify(
            "Not a PDF file\n\n"
            + html.escape(TITLE[:150])
            + "\n\nSource returned non-PDF content"
        )
        sys.exit(1)

    # --- Проверка размера ---
    if size_mb > GITHUB_HARD_LIMIT_MB:
        dest.unlink()
        log("too big: " + format(size_mb, ".1f") + " MB")
        notify(
            "File > 100 MB\n\n"
            + html.escape(TITLE[:150])
            + "\n\n" + format(size_mb, ".1f") + " MB"
            + "\n\nDownload manually:\n" + URL
        )
        return

    # --- Успех ---
    log("saved: " + filename + " (" + format(size_mb, ".1f") + " MB)")
    notify(
        "Downloaded\n\n"
        + html.escape(TITLE[:150])
        + "\n\n" + filename
        + "\n" + format(size_mb, ".1f") + " MB"
        + "\n\nTo make audio: use /audio"
    )


if __name__ == "__main__":
    main()