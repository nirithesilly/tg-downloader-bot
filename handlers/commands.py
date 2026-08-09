import asyncio
import html
import logging
import platform
import re
import time

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from config import MAX_DOWNLOAD_SIZE_MB, MAX_FILE_SIZE_MB, PART_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.facebook import FacebookDownloader
from downloader.instagram import InstagramDownloader
from downloader.spotify import SpotifyDownloader
from downloader.tiktok import TikTokDownloader
from downloader.youtube import YouTubeDownloader
from utils.download_manager import DownloadCancelled, download_manager
from utils.files import (
    cleanup_temp_file,
    get_file_size_mb,
    merge_instructions,
    split_file,
)

router = Router()
yt_downloader = YouTubeDownloader()
tiktok_downloader = TikTokDownloader()
instagram_downloader = InstagramDownloader()
facebook_downloader = FacebookDownloader()
spotify_downloader = SpotifyDownloader()

USER_URL_TTL = 600
MAX_USER_URLS = 200

user_urls = {}


def store_url(user_id: int, url: str, service: str):
    if len(user_urls) > MAX_USER_URLS:
        now = time.time()
        for uid in [uid for uid, d in user_urls.items()
                    if now - d.get("ts", 0) > USER_URL_TTL]:
            user_urls.pop(uid, None)
    user_urls[user_id] = {"url": url, "service": service, "ts": time.time()}


def get_url(user_id: int):
    data = user_urls.get(user_id)
    if not data:
        return None
    if time.time() - data["ts"] > USER_URL_TTL:
        user_urls.pop(user_id, None)
        return None
    return data


def pop_url(user_id: int):
    data = get_url(user_id)
    if data:
        user_urls.pop(user_id, None)
    return data


def cancel_kb(job_id: str):
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="отмена", callback_data=f"cancel:{job_id}")
    ]])


async def safe_answer(callback: types.CallbackQuery, text: str, **kwargs):
    try:
        await callback.answer(text, **kwargs)
    except Exception:
        pass


def esc(text) -> str:
    return html.escape(str(text))


def log_error(context: str, error: Exception):
    logging.error("Ошибка в %s: %s", context, error, exc_info=True)


def generic_error(context: str, error: Exception) -> str:
    log_error(context, error)
    return (
        f"<b>ошибка {context}:</b>\n"
        "не получилось. отправь ссылку ещё раз или попробуй позже.\n"
        "если повторяется — сообщи @nirithesilly"
    )


async def download_with_progress(message: types.Message, func, *args,
                                 waiting_text="скачиваю...", token=None, job_id=None, **kwargs):
    status = {'text': ''}

    def hook(d):
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

    last_text = None
    grace_start = None
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


async def run_download(callback: types.CallbackQuery, waiting_text: str, func, *args, **kwargs):
    job = download_manager.create_job(callback.from_user.id)
    try:
        async def position_cb(pos):
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


async def too_large(callback: types.CallbackQuery, size_mb: float):
    try:
        await callback.message.edit_text(
            f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_DOWNLOAD_SIZE_MB} мб)\n"
            "отправь ссылку ещё раз и выбери меньшее качество, если доступно.",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def download_and_check(callback: types.CallbackQuery, waiting_text: str, func, *args, **kwargs):
    filepath, cancelled = await run_download(callback, waiting_text, func, *args, **kwargs)
    if cancelled:
        return None, True
    size_mb = get_file_size_mb(filepath)
    if size_mb > MAX_DOWNLOAD_SIZE_MB:
        cleanup_temp_file(filepath)
        await too_large(callback, size_mb)
        return None, True
    return filepath, False


async def send_media(callback: types.CallbackQuery, filepath: str, media_type: str, caption: str):
    file = FSInputFile(filepath)
    if media_type == "audio":
        await callback.message.answer_audio(audio=file, caption=caption, parse_mode="HTML")
    elif media_type == "video":
        await callback.message.answer_video(video=file, caption=caption, parse_mode="HTML")
    else:
        await callback.message.answer_document(document=file, caption=caption, parse_mode="HTML")
    cleanup_temp_file(filepath)
    await callback.message.delete()


async def send_media_split(callback: types.CallbackQuery, filepath: str, media_type: str, caption: str):
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


# --- КОМАНДА /start ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    name = esc(message.from_user.first_name.lower() if message.from_user and message.from_user.first_name else "друг")
    await message.answer(
        f"<b>привет, {name}.</b>\n\n"
        "я - <b>media downloader bot</b>.\n"
        "отправь мне ссылку на видео или трек из youtube, instagram, tiktok, facebook или spotify, "
        "и я скачаю его для тебя.\n\n"
        "<b>поддерживаемые сервисы:</b>\n"
        "youtube - видео/аудио\n"
        "instagram - видео/фото\n"
        "tiktok - видео (без водяного знака)/аудио\n"
        "facebook - видео/аудио\n"
        "spotify - треки (mp3)\n\n"
        "<b>команды:</b>\n"
        "/help - как пользоваться\n"
        "/about - о боте\n\n"
        "<b>просто отправь ссылку.</b>",
        parse_mode="HTML"
    )

# --- КОМАНДА /help ---
@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>как пользоваться ботом</b>\n\n"
        "1. <b>отправь ссылку</b>\n"
        "скопируй ссылку на медиа из поддерживаемого сервиса и отправь боту.\n\n"
        "2. <b>выбери формат</b>\n"
        "бот определит сервис и предложит варианты:\n"
        "• youtube: видео (best/720p/480p) или mp3\n"
        "• instagram: видео/reels или фото\n"
        "• tiktok: видео без водяного знака или mp3\n"
        "• facebook: видео (best/720p/480p) или mp3\n"
        "• spotify: скачивание трека в mp3\n\n"
        "3. <b>получи файл</b>\n"
        "дождись загрузки - бот отправит готовый файл.\n\n"
        "<b>важно:</b>\n"
        "• файлы до 50 мб отправляются как есть\n"
        "• файлы больше 50 мб отправляются по частям (склей по инструкции)\n"
        "• файлы автоматически удаляются с сервера после отправки\n"
        "• приватные аккаунты instagram не поддерживаются\n\n"
        "<b>проблемы?</b> пиши @nirithesilly",
        parse_mode="HTML"
    )

# --- КОМАНДА /about ---
@router.message(Command("about"))
async def cmd_about(message: types.Message):
    await message.answer(
        "<b>о боте</b>\n\n"
        "<b>название:</b> media downloader bot\n"
        "<b>версия:</b> 2.1.0\n"
        "<b>автор:</b> @nirithesilly\n\n"
        "<b>технологии:</b>\n"
        f"• python {platform.python_version()}\n"
        "• aiogram 3\n"
        "• yt-dlp\n"
        "• ffmpeg\n\n"
        "<b>статус сервисов:</b>\n"
        "youtube - полностью работает\n"
        "instagram - работает (reels + фото)\n"
        "tiktok - полностью работает (без водяного знака)\n"
        "facebook - полностью работает\n"
        "spotify - полностью работает\n\n"
        "<b>обратная связь:</b>\n"
        "по всем вопросам и предложениям:\n"
        "@nirithesilly",
        parse_mode="HTML"
    )

# --- ОПРЕДЕЛЕНИЕ СЕРВИСА ---
def detect_service(url: str) -> str:
    if re.search(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:youtube\.com|youtu\.be)', url):
        return "youtube"
    elif re.search(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)', url):
        return "tiktok"
    elif re.search(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:instagram\.com|instagr\.am)', url):
        return "instagram"
    elif re.search(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:facebook\.com|fb\.watch|fb\.com|fb\.me)', url):
        return "facebook"
    elif re.search(r'https?://(?:[a-zA-Z0-9_-]+\.)?(?:open\.spotify\.com/(?:track|album|playlist|episode|show)|spotify\.link)', url):
        return "spotify"
    else:
        return "unknown"

# --- YOUTUBE ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "youtube")
async def handle_youtube(message: types.Message):
    url = message.text.strip()
    store_url(message.from_user.id, url, "youtube")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, yt_downloader.get_info, url)

        if info.get('_type') == 'playlist' or info.get('entries'):
            await message.answer(
                "<b>плейлисты не поддерживаются.</b>\n"
                "отправь ссылку на отдельное видео:\n"
                "<code>youtube.com/watch?v=...</code>\n"
                "<code>youtu.be/...</code>\n"
                "<code>youtube.com/shorts/...</code>",
                parse_mode="HTML"
            )
            return

        duration = info.get('duration') or 0
        duration_min = duration // 60
        duration_sec = duration % 60

        title_str = esc(str(info.get('title', '')).lower()[:100])
        uploader_str = esc(str(info.get('uploader', '')).lower())

        await message.answer(
            f"<b>youtube видео найдено.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>длительность:</b> {duration_min}:{duration_sec:02d}\n\n"
            f"<b>выберите формат:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="видео", callback_data="yt_video"),
                    types.InlineKeyboardButton(text="аудио", callback_data="yt_audio")
                ],
                [
                    types.InlineKeyboardButton(text="720p", callback_data="yt_video_720"),
                    types.InlineKeyboardButton(text="480p", callback_data="yt_video_480")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("youtube", e), parse_mode="HTML")

# --- TIKTOK ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "tiktok")
async def handle_tiktok(message: types.Message):
    url = message.text.strip()
    store_url(message.from_user.id, url, "tiktok")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, tiktok_downloader.get_info, url)

        title_str = esc(str(info.get('title', '')).lower()[:100])
        uploader_str = esc(str(info.get('uploader', '')).lower())
        duration = info.get('duration') or 0

        await message.answer(
            f"<b>tiktok найден.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>длительность:</b> {duration} сек\n\n"
            f"<b>выберите формат:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="видео (без водяного знака)", callback_data="tt_video"),
                    types.InlineKeyboardButton(text="аудио (mp3)", callback_data="tt_audio")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("tiktok", e), parse_mode="HTML")

# --- INSTAGRAM ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "instagram")
async def handle_instagram(message: types.Message):
    url = message.text.strip()
    store_url(message.from_user.id, url, "instagram")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, instagram_downloader.get_info, url)

        content_type = info.get('content_type', 'photo')

        if content_type == "video":
            buttons = [
                [types.InlineKeyboardButton(text="видео/reels", callback_data="ig_video")]
            ]
            type_label = "видео/reels"
        else:
            buttons = [
                [types.InlineKeyboardButton(text="скачать фото", callback_data="ig_photo")]
            ]
            type_label = "фото"

        title_str = esc(str(info.get('title', '')).lower())
        uploader_str = esc(str(info.get('uploader', '')).lower())
        desc_str = esc(str(info.get('description', '')).lower()[:100])
        desc_len = len(str(info.get('description', '')))

        await message.answer(
            f"<b>instagram найден.</b>\n\n"
            f"<b>описание:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>текст:</b> {desc_str}{'...' if desc_len > 100 else ''}\n"
            f"<b>тип:</b> {type_label}\n\n"
            f"<b>выберите действие:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        await message.answer(generic_error("instagram", e), parse_mode="HTML")

# --- FACEBOOK ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "facebook")
async def handle_facebook(message: types.Message):
    url = message.text.strip()
    store_url(message.from_user.id, url, "facebook")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, facebook_downloader.get_info, url)

        title_str = esc(str(info.get('title', '')).lower()[:100])
        uploader_str = esc(str(info.get('uploader', '')).lower())

        await message.answer(
            f"<b>facebook видео найдено.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n\n"
            f"<b>выберите формат:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="видео", callback_data="fb_video"),
                    types.InlineKeyboardButton(text="аудио", callback_data="fb_audio")
                ],
                [
                    types.InlineKeyboardButton(text="720p", callback_data="fb_video_720"),
                    types.InlineKeyboardButton(text="480p", callback_data="fb_video_480")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("facebook", e), parse_mode="HTML")

# --- SPOTIFY ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "spotify")
async def handle_spotify(message: types.Message):
    url = message.text.strip()
    resolved_url = spotify_downloader.resolve_url(url)
    store_url(message.from_user.id, resolved_url, "spotify")

    if re.search(r'open\.spotify\.com/(?:album|playlist)/', resolved_url):
        await message.answer(
            "<b>поддерживаются только ссылки на отдельные треки spotify.</b>\n"
            "альбомы и плейлисты не поддерживаются — отправь ссылку на трек\n"
            "(open.spotify.com/track/...).",
            parse_mode="HTML"
        )
        pop_url(message.from_user.id)
        return

    if re.search(r'open\.spotify\.com/(?:episode|show)/', resolved_url):
        await message.answer(
            "<b>подкасты не поддерживаются.</b>\n"
            "бот умеет скачивать только треки (open.spotify.com/track/...).",
            parse_mode="HTML"
        )
        pop_url(message.from_user.id)
        return

    if not re.search(r'open\.spotify\.com/track/', resolved_url):
        await message.answer(
            "<b>поддерживаются только ссылки на треки spotify.</b>\n"
            "отправь ссылку вида open.spotify.com/track/...",
            parse_mode="HTML"
        )
        pop_url(message.from_user.id)
        return

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, spotify_downloader.get_info, resolved_url)

        title_str = esc(str(info.get('title', '')).lower())
        uploader_str = esc(str(info.get('uploader', '')).lower())

        duration = info.get('duration') or 0
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "—"
        explicit_str = "да" if info.get('is_explicit') else "нет"

        await message.answer(
            f"<b>spotify трек найден.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>исполнитель:</b> {uploader_str}\n"
            f"<b>длительность:</b> {duration_str}\n"
            f"<b>explicit:</b> {explicit_str}\n\n"
            f"<b>выберите действие:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="скачать mp3", callback_data="sp_audio")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("spotify", e), parse_mode="HTML")

# --- НЕИЗВЕСТНЫЙ СЕРВИС ---
@router.message(lambda msg: msg.text and msg.text.startswith("http"))
async def handle_unknown(message: types.Message):
    await message.answer(
        "<b>ссылка получена.</b>\n\n"
        "но этот сервис пока не поддерживается.\n"
        "поддерживается:\n"
        "• youtube\n"
        "• instagram\n"
        "• tiktok\n"
        "• facebook\n"
        "• spotify\n\n"
        "предложения по новым сервисам пиши @nirithesilly",
        parse_mode="HTML"
    )


async def handle_too_large(callback: types.CallbackQuery, error: FileTooLargeError):
    try:
        await callback.message.edit_text(
            f"<b>{esc(error)}</b>\n\n"
            "отправь ссылку ещё раз и выбери меньшее качество.",
            parse_mode="HTML"
        )
    except Exception:
        pass


# --- КОЛБЭКИ YOUTUBE ---
@router.callback_query(lambda c: c.data.startswith("yt_"))
async def callback_youtube(callback: types.CallbackQuery):
    await safe_answer(callback, "начинаю загрузку...")

    data = pop_url(callback.from_user.id)
    if not data or data.get("service") != "youtube":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data

    if action == "yt_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю аудио (mp3)...",
                yt_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "audio", "<b>аудио из youtube скачано.</b>")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("youtube", e), parse_mode="HTML")
        return

    quality = {
        "yt_video": ("best", "лучшего качества"),
        "yt_video_720": ("720p", "720p"),
        "yt_video_480": ("480p", "480p"),
    }.get(action)
    if not quality:
        return

    try:
        filepath, cancelled = await download_and_check(
            callback, f"скачиваю видео youtube ({quality[1]})...",
            yt_downloader.download_video, url, quality[0],
            max_size_mb=MAX_DOWNLOAD_SIZE_MB
        )
        if cancelled:
            return
        await send_media_split(callback, filepath, "video", "<b>видео из youtube скачано.</b>")
    except FileTooLargeError as e:
        await handle_too_large(callback, e)
    except Exception as e:
        await callback.message.edit_text(generic_error("youtube", e), parse_mode="HTML")

# --- КОЛБЭКИ TIKTOK ---
@router.callback_query(lambda c: c.data.startswith("tt_"))
async def callback_tiktok(callback: types.CallbackQuery):
    await safe_answer(callback, "начинаю загрузку...")

    data = pop_url(callback.from_user.id)
    if not data or data.get("service") != "tiktok":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data

    if action == "tt_video":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю видео из tiktok (без водяного знака)...",
                tiktok_downloader.download_video, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "video", "<b>видео из tiktok скачано.</b> (без водяного знака)")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")

    elif action == "tt_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю аудио из tiktok...",
                tiktok_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "audio", "<b>аудио из tiktok скачано.</b>")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")

# --- КОЛБЭКИ INSTAGRAM ---
@router.callback_query(lambda c: c.data.startswith("ig_"))
async def callback_instagram(callback: types.CallbackQuery):
    await safe_answer(callback, "начинаю загрузку...")

    data = pop_url(callback.from_user.id)
    if not data or data.get("service") != "instagram":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data

    if action == "ig_video":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю видео/reels из instagram...",
                instagram_downloader.download_video, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "video", "<b>видео из instagram скачано.</b>")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("instagram", e), parse_mode="HTML")

    elif action == "ig_photo":
        try:
            result, cancelled = await run_download(
                callback, "скачиваю фото из instagram...",
                instagram_downloader.download_photo, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            if isinstance(result, list):
                if not result:
                    raise Exception("фото не найдено")
                media = [types.InputMediaPhoto(media=FSInputFile(f)) for f in result]
                await callback.message.answer_media_group(media=media)
                for f in result:
                    cleanup_temp_file(f)
            else:
                size_mb = get_file_size_mb(result)
                if size_mb > MAX_FILE_SIZE_MB:
                    cleanup_temp_file(result)
                    await too_large(callback, size_mb)
                    return
                await callback.message.answer_photo(
                    photo=FSInputFile(result),
                    caption="<b>фото из instagram скачано.</b>",
                    parse_mode="HTML"
                )
                cleanup_temp_file(result)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("instagram", e), parse_mode="HTML")

# --- КОЛБЭКИ FACEBOOK ---
@router.callback_query(lambda c: c.data.startswith("fb_"))
async def callback_facebook(callback: types.CallbackQuery):
    await safe_answer(callback, "начинаю загрузку...")

    data = pop_url(callback.from_user.id)
    if not data or data.get("service") != "facebook":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data

    if action == "fb_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю аудио (mp3)...",
                facebook_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "audio", "<b>аудио из facebook скачано.</b>")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("facebook", e), parse_mode="HTML")
        return

    quality = {
        "fb_video": ("best", "лучшего качества"),
        "fb_video_720": ("720p", "720p"),
        "fb_video_480": ("480p", "480p"),
    }.get(action)
    if not quality:
        return

    try:
        filepath, cancelled = await download_and_check(
            callback, f"скачиваю видео facebook ({quality[1]})...",
            facebook_downloader.download_video, url, quality[0],
            max_size_mb=MAX_DOWNLOAD_SIZE_MB
        )
        if cancelled:
            return
        await send_media_split(callback, filepath, "video", "<b>видео из facebook скачано.</b>")
    except FileTooLargeError as e:
        await handle_too_large(callback, e)
    except Exception as e:
        await callback.message.edit_text(generic_error("facebook", e), parse_mode="HTML")

# --- КОЛБЭКИ SPOTIFY ---
@router.callback_query(lambda c: c.data.startswith("sp_"))
async def callback_spotify(callback: types.CallbackQuery):
    await safe_answer(callback, "начинаю загрузку...")

    data = pop_url(callback.from_user.id)
    if not data or data.get("service") != "spotify":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]

    if callback.data == "sp_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю трек из spotify (mp3)...",
                spotify_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            await send_media_split(callback, filepath, "audio", "<b>трек из spotify скачан.</b>")
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("spotify", e), parse_mode="HTML")

# --- ОТМЕНА ЗАГРУЗКИ ---
@router.callback_query(lambda c: c.data.startswith("cancel:"))
async def callback_cancel(callback: types.CallbackQuery):
    job_id = callback.data.split(":", 1)[1]
    found = download_manager.cancel(job_id)
    if found:
        await safe_answer(callback, "отменяю...")
    else:
        await safe_answer(callback, "загрузка уже завершена или отменена")
