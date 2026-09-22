# ============================================================
# Personal Books - FINDER
# ------------------------------------------------------------
# v8: NLLB-200 перевод (любой язык -> RU).
#     - убран Helsinki, используется translate.py
#     - batch-перевод титлов и summary
# v7: production-ready, карточки по одной.
# ------------------------------------------------------------
# Требования:
#   pip install requests transformers
#            sentencepiece torch langdetect
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

DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Перевод (NLLB) ---
sys.path.insert(0, str(SCRIPT_DIR))
TRANSLATE_AVAILABLE = False
try:
    from translate import translate_batch
    from translate import translate_to_ru
    from translate import is_russian
    from translate import save_cache
    TRANSLATE_AVAILABLE = True
except ImportError as e:
    print("WARN: translate.py missing: " + str(e))

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
MAX_CARDS = 30
TIMEOUT = 30


# ============================================================
# LOG
# ============================================================
def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print("[" + ts + "] " + str(msg), flush=True)


# ============================================================
# TRANSLATE WRAPPERS
# ============================================================
def ensure_russian(text):
    """Перевод на русский через NLLB."""
    if not text:
        return text
    if not TRANSLATE_AVAILABLE:
        return text
    if is_russian(text):
        return text
    return translate_to_ru(text) or text


def ensure_english(text):
    """Обратный перевод не делаем — NLLB сам."""
    return text


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
    text = re.sub(r'^["\']?p["\']?\s+', "", text)
    text = re.sub(r'^span>?\s*', "", text)
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
# SOURCES
# ============================================================
def search_arxiv(topic_en, limit=10):
    results = []
    queries = [
        'all:"' + topic_en + '"',
        "all:" + topic_en,
    ]
    for q in queries:
        try:
            r = requests.get(
                "http://export.arxiv.org/api/query",
                params={
                    "search_query": q,
                    "start": 0,
                    "max_results": limit,
                    "sortBy": "relevance",
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            entries = r.text.split("<entry>")[1:]
            for entry in entries:
                try:
                    t = entry.split("<title>")[1]
                    title = t.split("</title>")[0].strip()
                    title = " ".join(title.split())
                    link = entry.split("<id>")[1]
                    link = link.split("</id>")[0].strip()
                    arxiv_id = link.split("/abs/")[-1]
                    summary = ""
                    try:
                        s = entry.split("<summary>")[1]
                        summary = s.split("</summary>")[0]
                        summary = " ".join(summary.split())
                        summary = summary[:600]
                    except Exception:
                        pass
                    dup = False
                    for x in results:
                        if x["url"].endswith(
                            arxiv_id + ".pdf",
                        ):
                            dup = True
                            break
                    if dup:
                        continue
                    results.append({
                        "title": title,
                        "summary": summary,
                        "url": "https://arxiv.org/pdf/"
                               + arxiv_id + ".pdf",
                        "page_url": link,
                        "source": "arxiv",
                        "type": "paper",
                    })
                except Exception:
                    continue
            if len(results) >= 3:
                break
        except Exception as e:
            log("arxiv: " + str(e))
    return results


def search_zenodo(topic_en, limit=10):
    results = []
    queries = ['"' + topic_en + '"', topic_en]
    for q in queries:
        try:
            r = requests.get(
                "https://zenodo.org/api/records",
                params={
                    "q": q,
                    "size": limit,
                    "file_type": "pdf",
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            hits = r.json().get("hits", {}).get("hits", [])
            for hit in hits:
                try:
                    meta = hit.get("metadata", {})
                    title = meta.get("title", "?")
                    desc = (meta.get("description") or "")
                    desc = desc[:600]
                    rec_id = hit.get("id")
                    pdf_url = None
                    size = 0
                    for f in hit.get("files", []):
                        key = f.get("key", "").lower()
                        if key.endswith(".pdf"):
                            pdf_url = f["links"]["self"]
                            size = f.get("size", 0)
                            break
                    if not pdf_url:
                        continue
                    if size / 1024 / 1024 > 100:
                        continue
                    dup = False
                    for x in results:
                        if x["url"] == pdf_url:
                            dup = True
                            break
                    if dup:
                        continue
                    results.append({
                        "title": title,
                        "summary": desc,
                        "url": pdf_url,
                        "page_url": "https://zenodo.org/records/"
                                    + str(rec_id),
                        "source": "zenodo",
                        "type": "book",
                        "size_mb": round(
                            size / 1024 / 1024, 1,
                        ),
                    })
                except Exception:
                    continue
            if len(results) >= 3:
                break
        except Exception as e:
            log("zenodo: " + str(e))
    return results


def search_semantic(topic_en, limit=10):
    results = []
    try:
        r = requests.get(
            "https://api.semanticscholar.org"
            + "/graph/v1/paper/search",
            params={
                "query": topic_en,
                "limit": limit,
                "fields": "title,abstract,openAccessPdf",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for item in r.json().get("data", []):
            pdf = item.get("openAccessPdf")
            if not pdf or not pdf.get("url"):
                continue
            results.append({
                "title": item.get("title", "?"),
                "summary": (item.get("abstract") or "")[:600],
                "url": pdf["url"],
                "source": "semantic_scholar",
                "type": "paper",
            })
    except Exception as e:
        log("ss: " + str(e))
    return results


# ============================================================
# RELEVANCE
# ============================================================
def _words_present(text, words):
    hits = 0
    for w in words:
        pat = r"\b" + re.escape(w) + r"\b"
        if re.search(pat, text):
            hits += 1
    return hits


def relevance_score(item, topic_en):
    text = item.get("title", "") + " "
    text += item.get("summary", "")
    text = text.lower()
    phrase = topic_en.lower().strip()

    if phrase and phrase in text:
        return 1.0

    words = [w for w in phrase.split() if len(w) > 2]
    distinctive = [w for w in words if len(w) >= 6]

    if distinctive:
        hits = _words_present(text, distinctive)
        if hits == 0:
            return 0.0
        return hits / len(distinctive)

    if words:
        hits = _words_present(text, words)
        if hits == len(words):
            return 1.0
        return 0.0

    return 0.0


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
# TRANSLATE ITEMS
# ============================================================
def translate_items(items):
    """Batch-перевод всех titлов и summary на русский."""
    if not TRANSLATE_AVAILABLE:
        log("translate.py missing, skip")
        return

    titles = []
    summaries = []
    for it in items:
        titles.append(it.get("title", ""))
        summaries.append(it.get("summary", "")[:400])

    log("translating " + str(len(items)) + " titles...")
    tr_titles = translate_batch(titles)

    log("translating " + str(len(items)) + " summaries...")
    tr_summaries = translate_batch(summaries)

    for i, it in enumerate(items):
        orig = it.get("title", "")
        new_t = tr_titles[i]
        if new_t and new_t != orig:
            it["title"] = new_t
            it["title_original"] = orig
        new_s = tr_summaries[i]
        if new_s:
            it["summary"] = new_s

    save_cache()


# ============================================================
# MAIN
# ============================================================
def main():
    if len(sys.argv) < 2:
        log("Usage: personal_finder.py <topic>")
        sys.exit(1)

    topic = " ".join(sys.argv[1:]).strip()
    log("search: " + topic)
    log("=" * 50)

    all_items = []
    sources = [
        ("arXiv", search_arxiv),
        ("Zenodo", search_zenodo),
        ("Semantic Scholar", search_semantic),
    ]
    for name, fn in sources:
        log(name + "...")
        res = fn(topic, limit=10)
        log("  found: " + str(len(res)))
        all_items.extend(res)

    if not all_items:
        txt = "Search: " + html.escape(topic)
        txt += "\n\nNothing found."
        send_message(txt)
        return

    # Filter
    for it in all_items:
        it["score"] = relevance_score(it, topic)
    scored = [x for x in all_items if x["score"] > 0]
    scored.sort(key=lambda x: x["score"], reverse=True)

    log("after filter: " + str(len(scored)))
    log("=" * 50)

    if not scored:
        txt = "Search: " + html.escape(topic)
        txt += "\n\nNo relevant matches.\n"
        txt += "Try English title."
        send_message(txt)
        return

    # Translate
    to_show = scored[:MAX_CARDS]
    translate_items(to_show)

    # Save
    candidates = {
        "topic": topic,
        "generated_at": datetime.now(
            timezone.utc,
        ).isoformat(),
        "total": len(scored),
        "offset": PAGE_SIZE,
        "items": scored,
    }
    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(
            candidates, f,
            ensure_ascii=False, indent=2,
        )
    log("saved: " + CANDIDATES_FILE.name)

    # Header
    total = len(scored)
    header = "Search: <b>" + html.escape(topic) + "</b>\n\n"
    header += "Found: <b>" + str(total) + "</b> items\n"
    header += "Showing first " + str(PAGE_SIZE) + ":"
    send_message(header)

    # Cards
    for i in range(PAGE_SIZE):
        if i >= len(to_show):
            break
        item = to_show[i]
        card_text = format_card(i + 1, item, PAGE_SIZE)
        kb = {
            "inline_keyboard": [[
                {
                    "text": "Download",
                    "callback_data": "personal_dl:"
                                     + str(i),
                },
                {
                    "text": "Reject",
                    "callback_data": "personal_reject:"
                                     + str(i),
                },
            ]],
        }
        send_message(card_text, kb)
        log("card sent: " + str(i + 1))

    # Show more
    if len(scored) > PAGE_SIZE:
        left = len(scored) - PAGE_SIZE
        kb = {
            "inline_keyboard": [[
                {
                    "text": "Show more (" + str(left) + ")",
                    "callback_data": "personal_next:0",
                },
            ]],
        }
        send_message(
            "Total found: " + str(total),
            kb,
        )

    log("done")


if __name__ == "__main__":
    main()