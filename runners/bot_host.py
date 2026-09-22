# ============================================================
# Personal Books - BOT HOST v2
# ------------------------------------------------------------
# v2: production-ready.
#     - personal_next теперь через workflow (единый формат)
#     - добавлена команда /next
#     - добавлена команда /audio <имя>
#     - логи с timestamp
#     - короткие строки
# ------------------------------------------------------------
# Требования: aiogram, python-dotenv, requests
# ============================================================

import os
import sys
import logging
import requests

try:
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command
    from aiogram.types import CallbackQuery
    from aiogram.types import InlineKeyboardMarkup
    from aiogram.types import InlineKeyboardButton
except ImportError as e:
    print("ERR: aiogram not installed")
    print(str(e))
    print("pip install aiogram==3.13.0")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("WARN: python-dotenv not installed")


BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
GITHUB_PAT = (
    os.getenv("GH_PAT")
    or os.getenv("GITHUB_PAT")
    or ""
).strip()
GITHUB_REPO = (os.getenv("GITHUB_REPO") or "").strip()

if not BOT_TOKEN:
    print("ERR: BOT_TOKEN not set")
    sys.exit(1)
if not GITHUB_REPO:
    print("ERR: GITHUB_REPO not set")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
logger.info("BOT_TOKEN: " + str(len(BOT_TOKEN)) + " chars")
logger.info("GH_PAT: " + str(len(GITHUB_PAT)) + " chars")
logger.info("REPO: " + GITHUB_REPO)


# ------------------------------------------------------------
# WORKFLOWS
# ------------------------------------------------------------
WORKFLOWS = {
    "audio": {"file": "personal_audio.yml"},
    "find": {"file": "personal_find.yml"},
    "next": {"file": "personal_next.yml"},
    "download": {"file": "personal_download.yml"},
}


# ------------------------------------------------------------
# GITHUB API
# ------------------------------------------------------------
def run_workflow(key, inputs=None):
    wf = WORKFLOWS.get(key)
    if not wf:
        return False, "Unknown: " + str(key)
    url = "https://api.github.com/repos/"
    url += GITHUB_REPO
    url += "/actions/workflows/"
    url += wf["file"]
    url += "/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + GITHUB_PAT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = {"ref": "main"}
    if inputs:
        data["inputs"] = inputs
    try:
        r = requests.post(
            url, headers=headers, json=data, timeout=15,
        )
        if r.status_code in (200, 201, 204):
            return True, "OK"
        if r.status_code == 404:
            return False, "not found"
        if r.status_code == 403:
            return False, "no scope"
        return False, "HTTP " + str(r.status_code)
    except Exception as e:
        return False, str(e)


def read_json(path):
    url = "https://api.github.com/repos/"
    url += GITHUB_REPO
    url += "/contents/"
    url += path
    headers = {
        "Accept": "application/vnd.github.raw",
        "Authorization": "Bearer " + GITHUB_PAT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def list_dir(path):
    url = "https://api.github.com/repos/"
    url += GITHUB_REPO
    url += "/contents/"
    url += path
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + GITHUB_PAT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def delete_file(path, sha, message="delete"):
    url = "https://api.github.com/repos/"
    url += GITHUB_REPO
    url += "/contents/"
    url += path
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + GITHUB_PAT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = {"message": message, "sha": sha, "branch": "main"}
    try:
        r = requests.delete(
            url, headers=headers, json=data, timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


def send_dispatch(event_type, payload):
    url = "https://api.github.com/repos/"
    url += GITHUB_REPO
    url += "/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + GITHUB_PAT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = {
        "event_type": event_type,
        "client_payload": payload,
    }
    try:
        r = requests.post(
            url, headers=headers, json=data, timeout=15,
        )
        return r.status_code == 204
    except Exception:
        return False


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def personal_books():
    items = list_dir("personal_books")
    books = {}
    for it in items:
        n = it.get("name", "")
        if not n.endswith(".pdf"):
            continue
        stem = n[:-4]
        if stem.endswith("_RU"):
            base = stem[:-3]
            books.setdefault(base, {})["ru"] = n
        else:
            books.setdefault(stem, {})["en"] = n
    return books


def short_info():
    return (
        "Personal Books\n\n"
        "Личная библиотека.\n\n"
        "Команды:\n"
        "/find тема - поиск книг\n"
        "/findnext - ещё 5 книг\n"
        "/audio - список книг\n"
        "/audio имя - сделать mp3\n\n"
        "Или кнопки внизу."
    )


def help_text():
    return (
        "Personal Books - справка\n\n"
        "Поиск книг\n"
        "  /find тема\n"
        "  Пример: /find Schopenhauer\n"
        "  Источники: arXiv, Zenodo, Semantic Scholar\n\n"
        "Ещё результаты\n"
        "  /findnext\n"
        "  Показать следующие 5 книг\n\n"
        "Скачивание\n"
        "  После /find нажми [Download]\n"
        "  PDF попадёт в personal_books/\n\n"
        "Аудиокниги\n"
        "  /audio - список книг\n"
        "  /audio имя - сделать mp3 (RU)\n"
        "  PDF -> mp3, mp3 придут в Telegram\n"
        "  MP3 удаляются после отправки\n"
        "  PDF остаётся в репо\n\n"
        "Мои книги\n"
        "  /books или кнопка в меню\n"
        "  Там же аудио и удаление\n\n"
        "Советы\n"
        "  Аудио идёт частями по 45 минут\n"
        "  Длинная книга = 4-6 частей\n"
        "  Скан PDF не читается (нужен текстовый)\n"
        "  Файлы > 100 МБ не влезают"
    )


# ------------------------------------------------------------
# BOT
# ------------------------------------------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Найти книгу",
                callback_data="menu:find",
            ),
            InlineKeyboardButton(
                text="Мои книги",
                callback_data="menu:books",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Аудио",
                callback_data="menu:audio",
            ),
            InlineKeyboardButton(
                text="Помощь",
                callback_data="menu:help",
            ),
        ],
    ])


def kb_back(target="menu:main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=target,
            ),
        ],
    ])


def kb_books_list(books):
    rows = []
    for name in books[:10]:
        rows.append([
            InlineKeyboardButton(
                text=name[:40],
                callback_data="book:view:" + name,
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="Обновить",
            callback_data="menu:books",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="menu:main",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_book_actions(name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Аудио (RU)",
                callback_data="book:audio:" + name,
            ),
        ],
        [
            InlineKeyboardButton(
                text="Аудио (EN)",
                callback_data="book:audio_en:" + name,
            ),
        ],
        [
            InlineKeyboardButton(
                text="Удалить",
                callback_data="book:del:" + name,
            ),
            InlineKeyboardButton(
                text="Назад",
                callback_data="menu:books",
            ),
        ],
    ])


def kb_confirm(action, payload=""):
    cb_yes = "confirm:" + action
    if payload:
        cb_yes += ":" + payload
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Да",
                callback_data=cb_yes,
            ),
            InlineKeyboardButton(
                text="Отмена",
                callback_data="menu:main",
            ),
        ],
    ])


# ------------------------------------------------------------
# COMMANDS
# ------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        short_info(),
        reply_markup=kb_main(),
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        help_text(),
        reply_markup=kb_main(),
        disable_web_page_preview=True,
    )


@dp.message(Command("find"))
async def cmd_find(message: types.Message):
    t = message.text.replace("/find", "", 1).strip()
    if not t:
        await message.answer(
            "Напиши: /find тема\n"
            "Пример: /find Schopenhauer"
        )
        return
    await message.answer(
        "Ищу книги: " + t + "\n\n30-60 секунд..."
    )
    send_dispatch("personal_find", {
        "topic": t,
        "chat_id": str(message.chat.id),
    })


@dp.message(Command("findnext"))
async def cmd_findnext(message: types.Message):
    await message.answer("Загружаю следующие...")
    send_dispatch("personal_next", {})


@dp.message(Command("next"))
async def cmd_next(message: types.Message):
    await message.answer("Загружаю следующие...")
    send_dispatch("personal_next", {})


@dp.message(Command("audio"))
async def cmd_audio(message: types.Message):
    args = message.text.replace("/audio", "", 1).strip()
    if not args:
        await show_books_for_audio(message)
        return

    name = args
    await message.answer(
        "Аудио: " + name
        + "\n\nЗапускаю обработку..."
    )
    ok, msg = run_workflow("audio", {
        "book": name,
        "prefer": "ru",
    })
    if not ok:
        await message.answer("Ошибка: " + msg)


@dp.message(Command("books"))
async def cmd_books(message: types.Message):
    books = personal_books()
    if not books:
        await message.answer(
            "Книг нет.\nНайди через /find"
        )
        return
    names = sorted(books.keys())
    await message.answer(
        "Мои книги (" + str(len(names)) + "):",
        reply_markup=kb_books_list(names),
    )


async def show_books_for_audio(message):
    books = personal_books()
    if not books:
        await message.answer(
            "Книг нет.\nНайди через /find и скачай."
        )
        return
    names = sorted(books.keys())
    await message.answer(
        "Аудио - выбери книгу:",
        reply_markup=kb_books_list(names),
    )


# ------------------------------------------------------------
# CALLBACKS - MENU
# ------------------------------------------------------------
@dp.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery):
    await cb.message.edit_text(
        short_info(),
        reply_markup=kb_main(),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:find")
async def cb_find(cb: CallbackQuery):
    await cb.message.edit_text(
        "Поиск книг\n\n"
        "Напиши:\n/find тема\n\n"
        "Пример:\n/find Schopenhauer",
        reply_markup=kb_back(),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(
        help_text(),
        reply_markup=kb_main(),
        disable_web_page_preview=True,
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:audio")
async def cb_audio_menu(cb: CallbackQuery):
    books = personal_books()
    if not books:
        await cb.message.edit_text(
            "Книг нет.\nНайди через /find.",
            reply_markup=kb_back(),
        )
        await cb.answer()
        return
    names = sorted(books.keys())
    await cb.message.edit_text(
        "Аудио - выбери книгу:",
        reply_markup=kb_books_list(names),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:books")
async def cb_books(cb: CallbackQuery):
    books = personal_books()
    if not books:
        await cb.message.edit_text(
            "Книг нет.\nНайди через /find.",
            reply_markup=kb_back(),
        )
        await cb.answer()
        return
    names = sorted(books.keys())
    await cb.message.edit_text(
        "Мои книги (" + str(len(names)) + "):",
        reply_markup=kb_books_list(names),
    )
    await cb.answer()


# ------------------------------------------------------------
# CALLBACKS - BOOK VIEW
# ------------------------------------------------------------
@dp.callback_query(F.data.startswith("book:view:"))
async def cb_book_view(cb: CallbackQuery):
    name = cb.data.replace("book:view:", "", 1)
    books = personal_books()
    if name not in books:
        await cb.answer("Не найдено", show_alert=True)
        return
    variants = books[name]
    flags = []
    if "ru" in variants:
        flags.append("RU")
    if "en" in variants:
        flags.append("EN")

    text = "Книга: " + name + "\n"
    text += "Форматы: " + " + ".join(flags)

    await cb.message.edit_text(
        text,
        reply_markup=kb_book_actions(name),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("book:audio:"))
async def cb_book_audio(cb: CallbackQuery):
    name = cb.data.replace("book:audio:", "", 1)
    await cb.answer("Запускаю...")
    ok, msg = run_workflow("audio", {
        "book": name,
        "prefer": "ru",
    })
    if ok:
        await cb.message.edit_text(
            "Аудио (RU): " + name
            + "\n\n5-15 минут.\nmp3 придут частями.",
            reply_markup=kb_book_actions(name),
        )
    else:
        await cb.message.edit_text(
            "Ошибка: " + msg,
            reply_markup=kb_book_actions(name),
        )


@dp.callback_query(F.data.startswith("book:audio_en:"))
async def cb_book_audio_en(cb: CallbackQuery):
    name = cb.data.replace("book:audio_en:", "", 1)
    await cb.answer("Запускаю...")
    ok, msg = run_workflow("audio", {
        "book": name,
        "prefer": "en",
    })
    if ok:
        await cb.message.edit_text(
            "Аудио (EN): " + name
            + "\n\n5-15 минут.",
            reply_markup=kb_book_actions(name),
        )
    else:
        await cb.message.edit_text(
            "Ошибка: " + msg,
            reply_markup=kb_book_actions(name),
        )


@dp.callback_query(F.data.startswith("book:del:"))
async def cb_book_del(cb: CallbackQuery):
    name = cb.data.replace("book:del:", "", 1)
    await cb.message.edit_text(
        "Удалить книгу?\n\n" + name
        + "\n\nБудут удалены все PDF.",
        reply_markup=kb_confirm("book_del", name),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("confirm:book_del:"))
async def cb_confirm_book_del(cb: CallbackQuery):
    name = cb.data.replace(
        "confirm:book_del:", "", 1,
    )
    items = list_dir("personal_books")
    deleted = 0
    for it in items:
        fname = it.get("name", "")
        if not fname.endswith(".pdf"):
            continue
        stem = fname[:-4]
        base = stem[:-3] if stem.endswith("_RU") else stem
        if base != name:
            continue
        ok = delete_file(
            "personal_books/" + fname,
            it.get("sha", ""),
            message="delete: " + name,
        )
        if ok:
            deleted += 1
    await cb.message.edit_text(
        "Удалено файлов: " + str(deleted),
        reply_markup=kb_back("menu:books"),
    )
    await cb.answer()


# ------------------------------------------------------------
# CALLBACKS - SEARCH RESULTS
# ------------------------------------------------------------
@dp.callback_query(F.data.startswith("personal_dl:"))
async def cb_pdl(cb: CallbackQuery):
    idx = cb.data.replace("personal_dl:", "")
    await cb.answer("Запускаю...")

    cand = read_json("data/personal_candidates.json")
    if not cand:
        await cb.message.edit_text("Нет списка")
        return

    items = cand.get("items", [])
    try:
        i = int(idx)
    except ValueError:
        await cb.answer("Ошибка", show_alert=True)
        return

    if i < 0 or i >= len(items):
        await cb.answer("Вне диапазона", show_alert=True)
        return

    item = items[i]
    url = item.get("url")
    title = item.get("title", "book")

    if not url:
        await cb.message.edit_text("Нет URL")
        return

    send_dispatch("personal_download", {
        "url": url,
        "title": title,
    })

    await cb.message.edit_text(
        "Скачиваю:\n\n" + title[:150]
        + "\n\n1-2 минуты.\n"
        + "PDF появится в personal_books/"
    )


@dp.callback_query(F.data.startswith("personal_reject:"))
async def cb_personal_reject(cb: CallbackQuery):
    await cb.answer("Отклонено")
    try:
        await cb.message.edit_reply_markup(
            reply_markup=None,
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("personal_next:"))
async def cb_pnext(cb: CallbackQuery):
    """Отправляем dispatch - workflow сам отрисует карточки."""
    await cb.answer("Загружаю...")
    send_dispatch("personal_next", {})
    try:
        await cb.message.edit_reply_markup(
            reply_markup=None,
        )
    except Exception:
        pass


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------
async def main():
    logger.info("Personal Books Bot v2 started")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")