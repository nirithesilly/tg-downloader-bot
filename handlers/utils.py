import asyncio
import html
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, Generator, Optional

from aiogram import types
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile

from config import MAX_DOWNLOAD_SIZE_MB, MAX_FILE_SIZE_MB, PART_SIZE_MB
from downloader.base import FileTooLargeError
from utils.download_manager import DownloadCancelled, download_manager
from utils.files import cleanup_temp_file, get_file_size_mb, merge_instructions, split_file

logger = logging.getLogger(__name__)

SESSION_TTL = 3600
MAX_SESSIONS = 500

url_sessions: dict[str, dict] = {}
user_to_last_session: dict[int, str] = {}

SERVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("youtube", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:youtube\.com|youtu\.be)')),
    ("tiktok", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)')),
    ("instagram", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:instagram\.com|instagr\.am)')),
    ("facebook", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:facebook\.com|fb\.watch|fb\.com|fb\.me)')),
    ("spotify", re.compile(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:open\.spotify\.com/(?:track|album|playlist|episode|show)|spotify\.link)')),
]

URL_REGEX = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')


def extract_url(message: types.Message) -> Optional[str]:
    text = message.text or message.caption
    if not text:
        return None
    entities = message.entities or message.caption_entities
    if entities:
        for entity in entities:
            if entity.type == "url":
                raw = text[entity.offset:entity.offset + entity.length]
                return raw.rstrip('.,;!?:)]>')
            elif entity.type == "text_link" and entity.url:
                return entity.url.rstrip('.,;!?:)]>')
    match = URL_REGEX.search(text)
    if match:
        raw = match.group(1).rstrip('.,;!?:)]>')
        if raw.startswith("www."):
            raw = "https://" + raw
        return raw
    return None


def store_session(url: str, service: str, user_id: int, info: Optional[dict] = None) -> str:
    now = time.time()
    if len(url_sessions) > MAX_SESSIONS:
        expired = [sid for sid, d in url_sessions.items() if now - d.get("ts", 0) > SESSION_TTL]
        for sid in expired:
            url_sessions.pop(sid, None)
    sid = uuid.uuid4().hex[:8]
    url_sessions[sid] = {
        "sid": sid,
        "url": url,
        "service": service,
        "user_id": user_id,
        "info": info or {},
        "ts": now
    }
    user_to_last_session[user_id] = sid
    return sid


def get_session(session_or_user_id: Any) -> Optional[dict]:
    now = time.time()
    if isinstance(session_or_user_id, str):
        data = url_sessions.get(session_or_user_id)
        if data and now - data["ts"] <= SESSION_TTL:
            return data
    if isinstance(session_or_user_id, (int, str)):
        try:
            uid = int(session_or_user_id)
            sid = user_to_last_session.get(uid)
            if sid:
                data = url_sessions.get(sid)
                if data and now - data["ts"] <= SESSION_TTL:
                    return data
        except ValueError:
            pass
    return None


def pop_url(user_id: int) -> Optional[dict]:
    return get_session(user_id)


def store_url(user_id: int, url: str, service: str) -> str:
    return store_session(url, service, user_id)


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
    logger.error("Ошибка в %s: %s", context, error, exc_info=True)


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


def chunk_list(lst: list, n: int = 10) -> Generator[list, None, None]:
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


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
    last_edit_time: float = 0.0
    grace_start: Optional[float] = None
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), 3.0)
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
        now = time.monotonic()
        if text and text != last_text and (now - last_edit_time >= 3.0):
            last_text = text
            last_edit_time = now
            try:
                await message.edit_text(f"{waiting_text}\n<b>{esc(text)}</b>", parse_mode="HTML", reply_markup=kb)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
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
                     media_type: str, caption: str,
                     title: Optional[str] = None,
                     performer: Optional[str] = None,
                     duration: Optional[int] = None,
                     thumbnail: Optional[str] = None,
                     width: Optional[int] = None,
                     height: Optional[int] = None) -> None:
    try:
        file = FSInputFile(filepath)
        thumb_file = FSInputFile(thumbnail) if thumbnail and os.path.exists(thumbnail) else None
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        if media_type == "audio":
            await callback.message.answer_audio(
                audio=file, caption=caption, parse_mode="HTML",
                title=title, performer=performer, duration=duration, thumbnail=thumb_file
            )
        elif media_type == "video":
            await callback.message.answer_video(
                video=file, caption=caption, parse_mode="HTML",
                duration=duration, width=width, height=height, thumbnail=thumb_file,
                supports_streaming=True
            )
        else:
            await callback.message.answer_document(document=file, caption=caption, parse_mode="HTML")
    finally:
        cleanup_temp_file(filepath)
        if thumbnail:
            cleanup_temp_file(thumbnail)
        try:
            await callback.message.delete()
        except Exception:
            pass


async def send_media_split(callback: types.CallbackQuery, filepath: str,
                           media_type: str, caption: str, **kwargs: Any) -> None:
    size_mb = get_file_size_mb(filepath)
    if size_mb <= MAX_FILE_SIZE_MB:
        await send_media(callback, filepath, media_type, caption, **kwargs)
        return

    parts = split_file(filepath, PART_SIZE_MB)
    try:
        for i, part in enumerate(parts, 1):
            part_caption = f"{caption}\nчасть {i}/{len(parts)}" if i == 1 else f"часть {i}/{len(parts)}"
            if len(part_caption) > 1024:
                part_caption = part_caption[:1020] + "..."
            await callback.message.answer_document(
                document=FSInputFile(part),
                caption=part_caption,
                parse_mode="HTML"
            )
            cleanup_temp_file(part)
        await callback.message.answer(merge_instructions(), parse_mode="HTML")
    finally:
        for part in parts:
            cleanup_temp_file(part)
        cleanup_temp_file(filepath)
        thumb = kwargs.get('thumbnail')
        if thumb:
            cleanup_temp_file(thumb)
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

