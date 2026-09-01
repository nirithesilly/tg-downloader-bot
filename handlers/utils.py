import asyncio
import html
import logging
import re
import time
from typing import Any, Callable, Optional

from aiogram import types
from aiogram.types import FSInputFile

from config import MAX_DOWNLOAD_SIZE_MB, MAX_FILE_SIZE_MB, PART_SIZE_MB
from downloader.base import FileTooLargeError
from utils.download_manager import DownloadCancelled, download_manager
from utils.files import cleanup_temp_file, get_file_size_mb, merge_instructions, split_file

USER_URL_TTL = 600
MAX_USER_URLS = 200

user_urls: dict[int, dict] = {}

SERVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("youtube", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:youtube\.com|youtu\.be)')),
    ("tiktok", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)')),
    ("instagram", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:instagram\.com|instagr\.am)')),
    ("facebook", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:facebook\.com|fb\.watch|fb\.com|fb\.me)')),
    ("spotify", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:open\.spotify\.com/(?:track|album|playlist|episode|show)|spotify\.link)')),
]


def store_url(user_id: int, url: str, service: str) -> None:
    if len(user_urls) > MAX_USER_URLS:
        now = time.time()
        for uid in [uid for uid, d in user_urls.items()
                    if now - d.get("ts", 0) > USER_URL_TTL]:
            user_urls.pop(uid, None)
    user_urls[user_id] = {"url": url, "service": service, "ts": time.time()}


def get_url(user_id: int) -> Optional[dict]:
    data = user_urls.get(user_id)
    if not data:
        return None
    if time.time() - data["ts"] > USER_URL_TTL:
        user_urls.pop(user_id, None)
        return None
    return data


def pop_url(user_id: int) -> Optional[dict]:
    data = get_url(user_id)
    if data:
        user_urls.pop(user_id, None)
    return data


def cancel_kb(job_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="отмена", callback_data=f"cancel:{job_id}")
    ]])


async def safe_answer(callback: types.CallbackQuery, text: str, **kwargs: Any) -> None:
    try:
        await callback.answer(text, **kwargs)
    except Exception:
        pass


def esc(text: Any) -> str:
    return html.escape(str(text))


def log_error(context: str, error: Exception) -> None:
    logging.error("Ошибка в %s: %s", context, error, exc_info=True)


def generic_error(context: str, error: Exception) -> str:
    log_error(context, error)
    return (
        f"<b>ошибка {context}:</b>\n"
        "не получилось. отправь ссылку ещё раз или попробуй позже.\n"
        "если повторяется — сообщи @nirithesilly"
    )


def detect_service(url: str) -> str:
    for name, pattern in SERVICE_PATTERNS:
        if pattern.search(url):
            return name
    return "unknown"


async def download_with_progress(message: types.Message, func: Callable, *args: Any,
                                 waiting_text: str = "скачиваю...",
                                 token: Any = None, job_id: Optional[str] = None,
                                 **kwargs: Any) -> str:
    status: dict[str, str] = {'text': ''}

    def hook(d: dict) -> None:
        if token and token.cancelled:
            raise DownloadCancelled()
        if d.get('status') == 'downloading':
            status['text'] = (d.get('_percent_str') or '').strip() or ''
        elif d.get('status') == 'finished':
            status['text'] = 'обрабатываю...'

    kb = cancel_kb(job_id) if job_id else None
    try:
        await message.edit_text(waiting_text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass

    if token:
        kwargs['cancel_check'] = lambda: token.cancelled

    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(
        loop.run_in_executor(None, lambda: func(*args, **kwargs, progress_hook=hook))
    )

    last_text: Optional[str] = None
    grace_start: Optional[float] = None
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), 1.5)
        except asyncio.TimeoutError:
            pass
        if token and token.cancelled:
            if grace_start is None:
                grace_start = time.monotonic()
                try:
                    await message.edit_text("отменяю...", parse_mode="HTML", reply_markup=None)
                except Exception:
                    pass
            elif time.monotonic() - grace_start > 10:
                raise DownloadCancelled()
            continue
        text = status['text']
        if text and text != last_text:
            last_text = text
            try:
                await message.edit_text(f"{waiting_text}\n<b>{esc(text)}</b>", parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass

    return task.result()


async def run_download(callback: types.CallbackQuery, waiting_text: str,
                       func: Callable, *args: Any, **kwargs: Any) -> tuple[Optional[str], bool]:
    job = download_manager.create_job(callback.from_user.id)
    try:
        async def position_cb(pos: int) -> None:
            try:
                await callback.message.edit_text(
                    f"вы в очереди на загрузку.\n"
                    f"позиция в очереди: #{pos}\n"
                    f"сейчас загружается: {download_manager.active_count}/{download_manager.max_concurrent}",
                    parse_mode="HTML",
                    reply_markup=cancel_kb(job.job_id)
                )
            except Exception:
                pass

        acquired = await download_manager.wait_for_slot(job, position_cb=position_cb)
        if not acquired:
            try:
                await callback.message.edit_text("загрузка отменена.", parse_mode="HTML")
            except Exception:
                pass
            return None, True

        try:
            filepath = await download_with_progress(
                callback.message, func, *args, **kwargs,
                waiting_text=waiting_text, token=job.token, job_id=job.job_id
            )
            return filepath, False
        except DownloadCancelled:
            try:
                await callback.message.edit_text("загрузка отменена.", parse_mode="HTML")
            except Exception:
                pass
            return None, True
    finally:
        await download_manager.release_slot(job)


async def too_large(callback: types.CallbackQuery, size_mb: float) -> None:
    try:
        await callback.message.edit_text(
            f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_DOWNLOAD_SIZE_MB} мб)\n"
            "отправь ссылку ещё раз и выбери меньшее качество, если доступно.",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def download_and_check(callback: types.CallbackQuery, waiting_text: str,
                             func: Callable, *args: Any, **kwargs: Any) -> tuple[Optional[str], bool]:
    filepath, cancelled = await run_download(callback, waiting_text, func, *args, **kwargs)
    if cancelled:
        return None, True
    size_mb = get_file_size_mb(filepath)
    if size_mb > MAX_DOWNLOAD_SIZE_MB:
        cleanup_temp_file(filepath)
        await too_large(callback, size_mb)
        return None, True
    return filepath, False


async def send_media(callback: types.CallbackQuery, filepath: str,
                     media_type: str, caption: str) -> None:
    file = FSInputFile(filepath)
    if media_type == "audio":
        await callback.message.answer_audio(audio=file, caption=caption, parse_mode="HTML")
    elif media_type == "video":
        await callback.message.answer_video(video=file, caption=caption, parse_mode="HTML")
    else:
        await callback.message.answer_document(document=file, caption=caption, parse_mode="HTML")
    cleanup_temp_file(filepath)
    await callback.message.delete()


async def send_media_split(callback: types.CallbackQuery, filepath: str,
                           media_type: str, caption: str) -> None:
    size_mb = get_file_size_mb(filepath)
    if size_mb <= MAX_FILE_SIZE_MB:
        await send_media(callback, filepath, media_type, caption)
        return

    parts = split_file(filepath, PART_SIZE_MB)
    try:
        for i, part in enumerate(parts, 1):
            await callback.message.answer_document(
                document=FSInputFile(part),
                caption=f"{caption}\nчасть {i}/{len(parts)}" if i == 1 else f"часть {i}/{len(parts)}",
                parse_mode="HTML"
            )
            cleanup_temp_file(part)
        await callback.message.answer(merge_instructions(), parse_mode="HTML")
    finally:
        for part in parts:
            cleanup_temp_file(part)
        cleanup_temp_file(filepath)
        try:
            await callback.message.delete()
        except Exception:
            pass


async def handle_too_large(callback: types.CallbackQuery, error: FileTooLargeError) -> None:
    try:
        await callback.message.edit_text(
            f"<b>{esc(error)}</b>\n\n"
            "отправь ссылку ещё раз и выбери меньшее качество.",
            parse_mode="HTML"
        )
    except Exception:
        pass
