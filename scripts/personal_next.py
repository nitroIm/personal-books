# ============================================================
# Personal Books - NEXT PAGE
# ------------------------------------------------------------
# v2: production-ready.
#     - карточки по одной (как в finder)
#     - логи с timestamp
#     - чистка текста
#     - короткие строки
# ------------------------------------------------------------
# Требования: pip install requests
# ============================================================

import os
import sys
import json
import html
import re
import requests
from datetime import datetime, timezone
from pathlib import Path

# --- Пути ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = REPO_ROOT / "data"
CANDIDATES_FILE = DATA_DIR / "personal_candidates.json"

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

# --- Настройки ---
PAGE_SIZE = 5


# ============================================================
# LOG
# ============================================================
def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print("[" + ts + "] " + str(msg), flush=True)


# ============================================================
# CLEAN TEXT
# ============================================================
def clean_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"::", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r'^["\'\s]+', "", text)
    text = re.sub(r'["\'\s]+$', "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# TELEGRAM
# ============================================================
def send_message(text, keyboard=None):
    if not BOT_TOKEN or not CHAT_ID:
        log("no telegram - console")
        log(text[:500])
        return None
    try:
        payload = {
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        url = "https://api.telegram.org/bot"
        url += BOT_TOKEN + "/sendMessage"
        r = requests.post(
            url, json=payload, timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("result", {})
        log("tg " + str(r.status_code) + ": "
            + r.text[:150])
    except Exception as e:
        log("tg: " + str(e))
    return None


# ============================================================
# CARD
# ============================================================
def format_card(i, item, total):
    title = clean_text(item.get("title", "?"))
    title = html.escape(title)
    source = html.escape(item.get("source", "?"))
    size = item.get("size_mb")
    size_str = ""
    if size:
        size_str = " (" + str(size) + " MB)"

    lines = []
    lines.append("<b>" + str(i) + "/" + str(total) + "</b>")
    lines.append("<b>" + title + "</b>")
    lines.append("")
    lines.append("Source: " + source + size_str)
    lines.append("")

    summary = clean_text(item.get("summary", ""))
    if summary:
        short = summary[:280]
        if len(summary) > 280:
            short += "..."
        lines.append("<i>" + html.escape(short) + "</i>")
        lines.append("")

    page = item.get("page_url", item.get("url", ""))
    lines.append(
        '<a href="' + page + '">Open source</a>'
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    if not CANDIDATES_FILE.exists():
        log("no candidates file")
        send_message(
            "No saved results. Use /find first."
        )
        sys.exit(1)

    # --- Read JSON ---
    try:
        with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
            candidates = json.load(f)
    except Exception as e:
        log("read json: " + str(e))
        send_message("Cannot read search results")
        sys.exit(1)

    items = candidates.get("items", [])
    offset = candidates.get("offset", 0)
    topic = candidates.get("topic", "?")
    total = len(items)

    log("topic: " + topic)
    log("total: " + str(total))
    log("offset: " + str(offset))

    # --- All shown ---
    if offset >= total:
        send_message(
            "All items shown for: "
            + html.escape(topic)
        )
        log("nothing more")
        return

    # --- Next page ---
    next_page = items[offset:offset + PAGE_SIZE]
    end_idx = offset + len(next_page)
    remaining = total - end_idx

    log("showing " + str(offset + 1)
        + " - " + str(end_idx))

    # --- Header ---
    header = "More results for: <b>"
    header += html.escape(topic) + "</b>\n\n"
    header += "Showing " + str(offset + 1)
    header += "-" + str(end_idx)
    header += " of " + str(total)
    send_message(header)

    # --- Cards one by one ---
    for i, item in enumerate(next_page):
        global_idx = offset + i
        card_text = format_card(
            global_idx + 1, item, total,
        )
        kb = {
            "inline_keyboard": [[
                {
                    "text": "Download",
                    "callback_data": "personal_dl:"
                                     + str(global_idx),
                },
                {
                    "text": "Reject",
                    "callback_data": "personal_reject:"
                                     + str(global_idx),
                },
            ]],
        }
        send_message(card_text, kb)
        log("card sent: " + str(global_idx + 1))

    # --- Show more button ---
    if remaining > 0:
        kb = {
            "inline_keyboard": [[
                {
                    "text": "Show more ("
                            + str(remaining) + ")",
                    "callback_data": "personal_next:"
                                     + str(end_idx),
                },
            ]],
        }
        send_message(
            "Total found: " + str(total),
            kb,
        )

    # --- Update offset ---
    candidates["offset"] = end_idx
    try:
        with open(CANDIDATES_FILE, "w",
                  encoding="utf-8") as f:
            json.dump(
                candidates, f,
                ensure_ascii=False, indent=2,
            )
        log("offset updated: " + str(end_idx))
    except Exception as e:
        log("save json: " + str(e))

    log("done")


if __name__ == "__main__":
    main()