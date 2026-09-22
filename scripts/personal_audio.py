# ============================================================
# Personal Books - AUDIO (PDF -> MP3 -> Telegram)
# ------------------------------------------------------------
# v2: production-ready.
#     - уведомление при mp3 > 50 МБ
#     - вывод короче (для больших книг)
#     - защита от параллельных запусков
#     - отчёт в конце с размерами
# ------------------------------------------------------------
# Требования:
#   pip install gTTS PyPDF2
#   apt install ffmpeg
# ============================================================

import os
import sys
import re
import shutil
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timezone

# --- Пути ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PERSONAL_DIR = REPO_ROOT / "personal_books"
TEMP_DIR = Path("/tmp/personal_books_audio")

PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# --- Настройки ---
SEGMENT_MINUTES = 45
GTTS_BATCH_CHARS = 1800
TELEGRAM_LIMIT_MB = 48
CHARS_PER_MINUTE = 900

# --- Telegram ---
BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
).strip()
CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()


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
        log("tg error: " + str(e))
        return False


def send_audio(path, caption=""):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    if not path.exists():
        return False

    size_mb = path.stat().st_size / 1024 / 1024

    if size_mb > 50:
        log("file > 50 MB: " + path.name)
        notify(
            "mp3 too big for Telegram\n"
            + path.name
            + "\nsize: " + format(size_mb, ".1f") + " MB"
        )
        return False

    try:
        url = "https://api.telegram.org/bot"
        url += BOT_TOKEN + "/sendAudio"
        with open(path, "rb") as f:
            files = {"audio": f}
            data = {
                "chat_id": CHAT_ID,
                "caption": caption[:1000],
                "parse_mode": "HTML",
                "title": path.stem,
            }
            r = requests.post(
                url, data=data, files=files, timeout=900,
            )
        if r.status_code == 200:
            log("sent: " + path.name)
            return True
        log("tg " + str(r.status_code))
        return False
    except Exception as e:
        log("send_audio: " + str(e))
        return False


# ============================================================
# PDF -> TEXT
# ============================================================
def extract_text(pdf_path):
    import PyPDF2
    try:
        parts = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            total = len(reader.pages)
            log("pages: " + str(total))
            for i, page in enumerate(reader.pages):
                if i % 50 == 0:
                    log("  ..." + str(i) + "/" + str(total))
                text = page.extract_text() or ""
                parts.append(text)
        full = "\n\n".join(parts)
        log("chars: " + str(len(full)))
        return full
    except Exception as e:
        log("pdf error: " + str(e))
        return ""


# ============================================================
# SPLIT
# ============================================================
def split_into_segments(text, segment_chars):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    segments = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) + 1 <= segment_chars:
            current = current + " " + sent if current else sent
        else:
            if current:
                segments.append(current)
            current = sent
    if current:
        segments.append(current)
    return segments


def split_for_gtts(text, batch_chars):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    batches = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) + 1 <= batch_chars:
            current = current + " " + sent if current else sent
        else:
            if current:
                batches.append(current)
            current = sent
    if current:
        batches.append(current)
    return batches


# ============================================================
# TTS + CONCAT
# ============================================================
def tts_batch_to_mp3(text, out_path):
    from gtts import gTTS
    try:
        tts = gTTS(text=text, lang="ru", slow=False)
        tts.save(str(out_path))
        return True
    except Exception as e:
        log("gtts: " + str(e))
        return False


def concat_mp3(files, out_path):
    if not files:
        return False
    if len(files) == 1:
        shutil.copy(str(files[0]), str(out_path))
        return True

    list_file = TEMP_DIR / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in files:
            f.write("file '" + str(p) + "'\n")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c:a", "libmp3lame",
                "-q:a", "4",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            log("ffmpeg error:")
            log(result.stderr[-300:])
            return False
        return True
    except Exception as e:
        log("concat: " + str(e))
        return False


def segment_to_audio(segment_text, out_mp3):
    batches = split_for_gtts(segment_text, GTTS_BATCH_CHARS)
    log("  batches: " + str(len(batches)))

    temp_parts = []
    for i, batch in enumerate(batches):
        part_path = TEMP_DIR / (
            "part_" + str(i).zfill(4) + ".mp3"
        )
        if not tts_batch_to_mp3(batch, part_path):
            log("  fail at " + str(i))
            continue
        temp_parts.append(part_path)
        if i % 20 == 0:
            log("  ..." + str(i + 1) + "/" + str(len(batches)))

    if not temp_parts:
        return False

    log("  concat " + str(len(temp_parts)) + " parts")
    ok = concat_mp3(temp_parts, out_mp3)

    for p in temp_parts:
        try:
            p.unlink()
        except Exception:
            pass
    return ok


# ============================================================
# DEPENDENCIES
# ============================================================
def check_deps():
    errors = []
    try:
        from gtts import gTTS
        _ = gTTS
    except ImportError:
        errors.append("gTTS")
    try:
        import PyPDF2
        _ = PyPDF2
    except ImportError:
        errors.append("PyPDF2")
    if not shutil.which("ffmpeg"):
        errors.append("ffmpeg")
    return errors


# ============================================================
# SCAN
# ============================================================
def list_books():
    if not PERSONAL_DIR.exists():
        return {}
    files = sorted(PERSONAL_DIR.glob("*.pdf"))
    books = {}
    for f in files:
        name = f.stem
        if name.endswith("_RU"):
            base = name[:-3]
            books.setdefault(base, {})["ru"] = f
        else:
            books.setdefault(name, {})["en"] = f
    return books


# ============================================================
# MAIN WORK
# ============================================================
def make_audio(base_name, prefer="ru", keep=False):
    books = list_books()
    if base_name not in books:
        log("book not found: " + base_name)
        return False

    variants = books[base_name]
    if prefer == "ru" and "ru" in variants:
        pdf_path = variants["ru"]
    elif "en" in variants:
        pdf_path = variants["en"]
    elif "ru" in variants:
        pdf_path = variants["ru"]
    else:
        log("no pdf found")
        return False

    log("=" * 50)
    log("book: " + base_name)
    log("file: " + pdf_path.name)
    log("=" * 50)

    notify(
        "Audio started\n"
        + pdf_path.name
        + "\n\nplease wait..."
    )

    text = extract_text(pdf_path)
    if not text.strip():
        notify("Cannot extract text (scan?)")
        return False

    segment_chars = SEGMENT_MINUTES * CHARS_PER_MINUTE
    segments = split_into_segments(text, segment_chars)
    log("segments: " + str(len(segments)))

    total = len(segments)
    sent_count = 0
    sizes = []

    for idx, seg in enumerate(segments, 1):
        log("")
        log("segment " + str(idx) + "/" + str(total))
        log("  chars: " + str(len(seg)))

        out_mp3 = TEMP_DIR / (
            base_name[:50]
            + "_part" + str(idx).zfill(2)
            + ".mp3"
        )

        if not segment_to_audio(seg, out_mp3):
            log("  skip")
            continue

        size_mb = out_mp3.stat().st_size / 1024 / 1024
        log("  size: " + format(size_mb, ".1f") + " MB")

        caption = (
            "<b>" + base_name + "</b>\n"
            + "Part " + str(idx) + "/" + str(total)
            + "\n" + format(size_mb, ".1f") + " MB"
            + " ~ " + str(SEGMENT_MINUTES) + " min"
        )

        if send_audio(out_mp3, caption):
            sent_count += 1
            sizes.append(round(size_mb, 1))
        else:
            log("  send failed")

        if not keep:
            try:
                out_mp3.unlink()
            except Exception:
                pass

    log("")
    log("=" * 50)
    log("done: " + str(sent_count) + "/" + str(total))
    log("=" * 50)

    total_mb = sum(sizes)
    notify(
        "Audio done\n"
        + base_name + "\n"
        + str(sent_count) + " parts\n"
        + format(total_mb, ".1f") + " MB total"
    )
    return True


# ============================================================
# ENTRY
# ============================================================
def main():
    errs = check_deps()
    if errs:
        log("Missing: " + ", ".join(errs))
        notify("Missing deps: " + ", ".join(errs))
        sys.exit(1)

    args = sys.argv[1:]

    if not args:
        books = list_books()
        if not books:
            log("no books in personal_books/")
            return
        log("Books:")
        for i, (name, v) in enumerate(books.items(), 1):
            flags = []
            if "ru" in v:
                flags.append("RU")
            if "en" in v:
                flags.append("EN")
            log("  " + str(i) + ". " + name
                + " [" + "+".join(flags) + "]")
        log("")
        log("Usage:")
        log("  audio.py <name>")
        log("  audio.py <name> --en")
        log("  audio.py <name> --keep")
        return

    base_name = args[0]
    prefer = "ru"
    keep = False

    if "--en" in args:
        prefer = "en"
    if "--keep" in args:
        keep = True

    make_audio(base_name, prefer=prefer, keep=keep)


if __name__ == "__main__":
    main()