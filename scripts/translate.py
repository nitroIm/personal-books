# ============================================================
# Personal Books - TRANSLATE (any -> RU) v5
# ------------------------------------------------------------
# v5: fix зацикливания NLLB.
#     - no_repeat_ngram_size + repetition_penalty
#     - num_beams=1 (быстрее, стабильнее)
#     - looks_broken() откат к оригиналу
#     - защита от коротких чанков
# v4: NLLB-200 мультиязычный
# ============================================================
# Требования:
#   pip install transformers==4.41.2
#               sentencepiece
#               torch==2.2.0
#               langdetect
#               numpy<2
# ============================================================

import os
import json
import hashlib
import threading
from pathlib import Path
from collections import Counter

# --- Пути ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_FILE = DATA_DIR / "translation_cache.json"

# --- Настройки ---
MODEL_NAME = "facebook/nllb-200-distilled-600M"
TGT_LANG = "rus_Cyrl"
MAX_CHARS = 500
BATCH_SIZE = 8
CACHE_MAX_SIZE = 5000
MIN_TRANSLATE_CHARS = 8
BROKEN_RATIO = 0.5

# --- Карта языков ---
LANG_MAP = {
    "en": "eng_Latn",
    "es": "spa_Latn",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "zh-cn": "zho_Hans",
    "zh-tw": "zho_Hant",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "ar": "arb_Arab",
    "tr": "tur_Latn",
    "vi": "vie_Latn",
    "hi": "hin_Deva",
    "cs": "ces_Latn",
    "sv": "swe_Latn",
    "da": "dan_Latn",
    "fi": "fin_Latn",
    "no": "nob_Latn",
    "el": "ell_Grek",
    "he": "heb_Hebr",
    "hu": "hun_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "sr": "srp_Cyrl",
    "hr": "hrv_Latn",
}

# --- Внутреннее состояние ---
_model = None
_tokenizer = None
_lock = threading.Lock()
_cache = None


# ============================================================
# LOG
# ============================================================
def log(msg):
    print("[translate] " + str(msg), flush=True)


# ============================================================
# КЭШ
# ============================================================
def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            if not isinstance(_cache, dict):
                _cache = {}
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save_cache():
    if _cache is None:
        return
    try:
        if len(_cache) > CACHE_MAX_SIZE:
            keys = list(_cache.keys())
            new_cache = {
                k: _cache[k]
                for k in keys[-CACHE_MAX_SIZE:]
            }
            _cache.clear()
            _cache.update(new_cache)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("cache save failed: " + str(e))


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ============================================================
# LANG DETECT
# ============================================================
def detect_lang(text: str) -> str:
    try:
        from langdetect import detect
        return detect(text[:500])
    except Exception:
        return "en"


def get_nllb_code(lang: str) -> str:
    lang = lang.lower()
    if lang in LANG_MAP:
        return LANG_MAP[lang]
    short = lang[:2]
    if short in LANG_MAP:
        return LANG_MAP[short]
    return "eng_Latn"


# ============================================================
# GUARDS
# ============================================================
def looks_broken(text: str) -> bool:
    """Одно слово >50% всего текста = зацикливание."""
    if not text:
        return False
    words = text.split()
    if len(words) < 5:
        return False
    counts = Counter(words)
    top_word, top_count = counts.most_common(1)[0]
    ratio = top_count / len(words)
    if ratio > BROKEN_RATIO:
        return True
    # Если 3 последних слова одинаковые — тоже залип
    if len(words) >= 3:
        if words[-1] == words[-2] == words[-3]:
            return True
    return False


def _should_skip(text: str) -> bool:
    """Слишком короткий или мусор — не переводим."""
    t = text.strip()
    if len(t) < MIN_TRANSLATE_CHARS:
        return True
    # Только цифры / символы
    letters = sum(1 for c in t if c.isalpha())
    if letters < 3:
        return True
    return False


# ============================================================
# МОДЕЛЬ
# ============================================================
def _load_model():
    global _model, _tokenizer
    with _lock:
        if _model is None:
            import torch
            from transformers import (
                AutoModelForSeq2SeqLM,
                AutoTokenizer,
            )
            log("loading NLLB: " + MODEL_NAME)
            _tokenizer = AutoTokenizer.from_pretrained(
                MODEL_NAME,
                src_lang="eng_Latn",
            )
            _model = AutoModelForSeq2SeqLM.from_pretrained(
                MODEL_NAME
            )
            _model.eval()
            log("NLLB ready")
    return _model, _tokenizer


def _generate(model, tokenizer, texts):
    """Единая точка генерации с защитой от повторов."""
    import torch
    tokens = tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )
    with torch.no_grad():
        translated = model.generate(
            **tokens,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids(
                TGT_LANG
            ),
            max_new_tokens=400,
            num_beams=1,
            no_repeat_ngram_size=4,
            repetition_penalty=1.3,
            length_penalty=1.0,
        )
    return tokenizer.batch_decode(
        translated, skip_special_tokens=True
    )


# ============================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ
# ============================================================
def is_russian(text: str) -> bool:
    if not text:
        return False
    sample = text[:3000]
    letters = [c for c in sample if c.isalpha()]
    if not letters:
        return False
    cyr = sum(
        1 for c in letters
        if "\u0400" <= c <= "\u04ff"
    )
    return (cyr / len(letters)) > 0.5


def translate_to_ru(text: str) -> str:
    if not text or not text.strip():
        return text

    cache = _load_cache()
    key = _cache_key(text)
    if key in cache:
        return cache[key]

    if is_russian(text):
        cache[key] = text
        return text

    if _should_skip(text):
        cache[key] = text
        return text

    src_lang = detect_lang(text)
    nllb_src = get_nllb_code(src_lang)

    try:
        model, tokenizer = _load_model()
        tokenizer.src_lang = nllb_src
        truncated = text[:MAX_CHARS]
        decoded = _generate(
            model, tokenizer, [truncated]
        )
        result = decoded[0].strip() if decoded else ""

        if result and not looks_broken(result):
            cache[key] = result
            return result

        log("broken/empty, keeping original")
    except Exception as e:
        log("translate err: " + str(e))

    cache[key] = text
    return text


def translate_batch(texts: list) -> list:
    if not texts:
        return []

    cache = _load_cache()
    results = [None] * len(texts)
    to_translate_idx = []
    to_translate_texts = []
    to_translate_srcs = []

    # 1. Кэш / русский / мусор
    for i, text in enumerate(texts):
        if not text or not text.strip():
            results[i] = text
            continue
        key = _cache_key(text)
        if key in cache:
            results[i] = cache[key]
            continue
        if is_russian(text):
            cache[key] = text
            results[i] = text
            continue
        if _should_skip(text):
            cache[key] = text
            results[i] = text
            continue
        to_translate_idx.append(i)
        to_translate_texts.append(text[:MAX_CHARS])
        to_translate_srcs.append(detect_lang(text))

    if not to_translate_texts:
        return results

    # 2. Батч
    try:
        model, tokenizer = _load_model()

        for start in range(
            0, len(to_translate_texts), BATCH_SIZE
        ):
            batch = to_translate_texts[start:start + BATCH_SIZE]
            srcs = to_translate_srcs[start:start + BATCH_SIZE]

            unique_srcs = set(srcs)
            if len(unique_srcs) > 1:
                # Разные языки — по одному
                for j, text in enumerate(batch):
                    idx = to_translate_idx[start + j]
                    src = get_nllb_code(srcs[j])
                    tokenizer.src_lang = src
                    decoded = _generate(
                        model, tokenizer, [text]
                    )
                    result = (
                        decoded[0].strip() if decoded else ""
                    )
                    if result and not looks_broken(result):
                        results[idx] = result
                        cache[_cache_key(texts[idx])] = result
                    else:
                        results[idx] = texts[idx]
                        cache[_cache_key(texts[idx])] = texts[idx]
                continue

            # Один язык
            src = get_nllb_code(srcs[0])
            tokenizer.src_lang = src
            decoded = _generate(model, tokenizer, batch)

            for j, result in enumerate(decoded):
                idx = to_translate_idx[start + j]
                result = result.strip()
                if result and not looks_broken(result):
                    results[idx] = result
                    cache[_cache_key(texts[idx])] = result
                else:
                    log("broken chunk, keeping original")
                    results[idx] = texts[idx]
                    cache[_cache_key(texts[idx])] = texts[idx]

    except Exception as e:
        log("batch err: " + str(e))
        for idx in to_translate_idx:
            if results[idx] is None:
                results[idx] = texts[idx]

    _save_cache()
    return [
        r if r is not None else texts[i]
        for i, r in enumerate(results)
    ]


def save_cache():
    _save_cache()