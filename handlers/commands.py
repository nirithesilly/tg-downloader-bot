import asyncio
import html
import logging
import re
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from downloader.youtube import YouTubeDownloader
from downloader.tiktok import TikTokDownloader
from downloader.instagram import InstagramDownloader
from downloader.facebook import FacebookDownloader
from downloader.spotify import SpotifyDownloader
from downloader.base import FileTooLargeError
from config import MAX_FILE_SIZE_MB
from utils.files import cleanup_temp_file, get_file_size_mb

router = Router()
yt_downloader = YouTubeDownloader()
tiktok_downloader = TikTokDownloader()
instagram_downloader = InstagramDownloader()
facebook_downloader = FacebookDownloader()
spotify_downloader = SpotifyDownloader()

user_urls = {}


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
                                 waiting_text="скачиваю...", **kwargs):
    status = {'text': ''}

    def hook(d):
        if d.get('status') == 'downloading':
            status['text'] = (d.get('_percent_str') or '').strip() or ''
        elif d.get('status') == 'finished':
            status['text'] = 'обрабатываю...'

    try:
        await message.edit_text(waiting_text, parse_mode="HTML")
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(
        loop.run_in_executor(None, lambda: func(*args, **kwargs, progress_hook=hook))
    )

    last_text = None
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), 1.5)
        except asyncio.TimeoutError:
            pass
        text = status['text']
        if text and text != last_text:
            last_text = text
            try:
                await message.edit_text(f"{waiting_text}\n<b>{esc(text)}</b>", parse_mode="HTML")
            except Exception:
                pass

    return task.result()


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
        "<b>версия:</b> 2.0.0\n"
        "<b>автор:</b> @nirithesilly\n\n"
        "<b>технологии:</b>\n"
        "• python 3.13\n"
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
    elif re.search(r'https?://open\.spotify\.com/(?:track|album|playlist)', url):
        return "spotify"
    else:
        return "unknown"

# --- YOUTUBE ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "youtube")
async def handle_youtube(message: types.Message):
    url = message.text.strip()
    user_urls[message.from_user.id] = {"url": url, "service": "youtube"}

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, yt_downloader.get_info, url)

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
    user_urls[message.from_user.id] = {"url": url, "service": "tiktok"}

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
    user_urls[message.from_user.id] = {"url": url, "service": "instagram"}

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
    user_urls[message.from_user.id] = {"url": url, "service": "facebook"}

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
    user_urls[message.from_user.id] = {"url": url, "service": "spotify"}

    if not re.search(r'open\.spotify\.com/track/', url):
        await message.answer(
            "<b>поддерживаются только ссылки на треки spotify.</b>\n"
            "отправь ссылку вида open.spotify.com/track/...",
            parse_mode="HTML"
        )
        user_urls.pop(message.from_user.id, None)
        return

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, spotify_downloader.get_info, url)

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
    await callback.answer("начинаю загрузку...")

    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "youtube":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data
    user_urls.pop(callback.from_user.id, None)

    if action == "yt_audio":
        try:
            filepath = await download_with_progress(
                callback.message, yt_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю аудио (mp3)..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз и выбери меньшее качество.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            audio = FSInputFile(filepath)
            await callback.message.answer_audio(
                audio=audio,
                caption="<b>аудио скачано.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("youtube", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)
        return

    if action == "yt_video":
        quality, label = "best", "лучшего качества"
    elif action == "yt_video_720":
        quality, label = "720p", "720p"
    elif action == "yt_video_480":
        quality, label = "480p", "480p"
    else:
        return

    try:
        filepath = await download_with_progress(
            callback.message, yt_downloader.download_video, url, quality,
            max_size_mb=MAX_FILE_SIZE_MB, waiting_text=f"скачиваю видео ({label})..."
        )
        size_mb = get_file_size_mb(filepath)
        if size_mb > MAX_FILE_SIZE_MB:
            await callback.message.edit_text(
                f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз и выбери меньшее качество.",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            return
        video = FSInputFile(filepath)
        await callback.message.answer_document(
            document=video,
            caption="<b>видео скачано.</b>",
            parse_mode="HTML"
        )
        cleanup_temp_file(filepath)
        await callback.message.delete()
    except FileTooLargeError as e:
        await handle_too_large(callback, e)
    except Exception as e:
        await callback.message.edit_text(generic_error("youtube", e), parse_mode="HTML")
        if 'filepath' in locals():
            cleanup_temp_file(filepath)

# --- КОЛБЭКИ TIKTOK ---
@router.callback_query(lambda c: c.data.startswith("tt_"))
async def callback_tiktok(callback: types.CallbackQuery):
    await callback.answer("начинаю загрузку...")

    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "tiktok":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data
    user_urls.pop(callback.from_user.id, None)

    if action == "tt_video":
        try:
            filepath = await download_with_progress(
                callback.message, tiktok_downloader.download_video, url,
                max_size_mb=MAX_FILE_SIZE_MB,
                waiting_text="скачиваю видео из tiktok (без водяного знака)..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            video = FSInputFile(filepath)
            await callback.message.answer_video(
                video=video,
                caption="<b>видео из tiktok скачано.</b> (без водяного знака)",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)

    elif action == "tt_audio":
        try:
            filepath = await download_with_progress(
                callback.message, tiktok_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю аудио из tiktok..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            audio = FSInputFile(filepath)
            await callback.message.answer_audio(
                audio=audio,
                caption="<b>аудио из tiktok скачано.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)

# --- КОЛБЭКИ INSTAGRAM ---
@router.callback_query(lambda c: c.data.startswith("ig_"))
async def callback_instagram(callback: types.CallbackQuery):
    await callback.answer("начинаю загрузку...")

    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "instagram":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data
    user_urls.pop(callback.from_user.id, None)

    if action == "ig_video":
        try:
            filepath = await download_with_progress(
                callback.message, instagram_downloader.download_video, url,
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю видео/reels из instagram..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            video = FSInputFile(filepath)
            await callback.message.answer_video(
                video=video,
                caption="<b>видео из instagram скачано.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("instagram", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)

    elif action == "ig_photo":
        try:
            result = await download_with_progress(
                callback.message, instagram_downloader.download_photo, url,
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю фото из instagram..."
            )
            if isinstance(result, list):
                if not result:
                    raise Exception("фото не найдено")
                media = [types.InputMediaPhoto(media=FSInputFile(f)) for f in result]
                await callback.message.answer_media_group(media=media)
                for f in result:
                    cleanup_temp_file(f)
            else:
                photo = FSInputFile(result)
                await callback.message.answer_photo(
                    photo=photo,
                    caption="<b>фото из instagram скачано.</b>",
                    parse_mode="HTML"
                )
                cleanup_temp_file(result)
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(generic_error("instagram", e), parse_mode="HTML")
            if 'result' in locals():
                if isinstance(result, list):
                    for f in result:
                        cleanup_temp_file(f)
                else:
                    cleanup_temp_file(result)

# --- КОЛБЭКИ FACEBOOK ---
@router.callback_query(lambda c: c.data.startswith("fb_"))
async def callback_facebook(callback: types.CallbackQuery):
    await callback.answer("начинаю загрузку...")

    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "facebook":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return

    url = data["url"]
    action = callback.data
    user_urls.pop(callback.from_user.id, None)

    if action == "fb_audio":
        try:
            filepath = await download_with_progress(
                callback.message, facebook_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю аудио (mp3)..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз и выбери меньшее качество.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            audio = FSInputFile(filepath)
            await callback.message.answer_audio(
                audio=audio,
                caption="<b>аудио из facebook скачано.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("facebook", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)
        return

    if action == "fb_video":
        quality, label = "best", "лучшего качества"
    elif action == "fb_video_720":
        quality, label = "720p", "720p"
    elif action == "fb_video_480":
        quality, label = "480p", "480p"
    else:
        return

    try:
        filepath = await download_with_progress(
            callback.message, facebook_downloader.download_video, url, quality,
            max_size_mb=MAX_FILE_SIZE_MB, waiting_text=f"скачиваю видео facebook ({label})..."
        )
        size_mb = get_file_size_mb(filepath)
        if size_mb > MAX_FILE_SIZE_MB:
            await callback.message.edit_text(
                f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз и выбери меньшее качество.",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            return
        video = FSInputFile(filepath)
        await callback.message.answer_document(
            document=video,
            caption="<b>видео из facebook скачано.</b>",
            parse_mode="HTML"
        )
        cleanup_temp_file(filepath)
        await callback.message.delete()
    except FileTooLargeError as e:
        await handle_too_large(callback, e)
    except Exception as e:
        await callback.message.edit_text(generic_error("facebook", e), parse_mode="HTML")
        if 'filepath' in locals():
            cleanup_temp_file(filepath)

# --- КОЛБЭКИ SPOTIFY ---
@router.callback_query(lambda c: c.data.startswith("sp_"))
async def callback_spotify(callback: types.CallbackQuery):
    await callback.answer("начинаю загрузку...")

    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "spotify":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return

    url = data["url"]
    user_urls.pop(callback.from_user.id, None)

    if callback.data == "sp_audio":
        try:
            filepath = await download_with_progress(
                callback.message, spotify_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_FILE_SIZE_MB, waiting_text="скачиваю трек из spotify (mp3)..."
            )
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(
                    f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nотправь ссылку ещё раз.",
                    parse_mode="HTML"
                )
                cleanup_temp_file(filepath)
                return
            audio = FSInputFile(filepath)
            await callback.message.answer_audio(
                audio=audio,
                caption="<b>трек из spotify скачан.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("spotify", e), parse_mode="HTML")
            if 'filepath' in locals():
                cleanup_temp_file(filepath)
