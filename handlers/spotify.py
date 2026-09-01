import asyncio
import re

from aiogram import Router, types

from config import MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.spotify import SpotifyDownloader
from handlers.utils import (
    detect_service,
    download_and_check,
    esc,
    generic_error,
    handle_too_large,
    pop_url,
    safe_answer,
    send_media_split,
    store_url,
)

router = Router()
spotify_downloader = SpotifyDownloader()


@router.message(lambda msg: msg.text and detect_service(msg.text) == "spotify")
async def handle_spotify(message: types.Message) -> None:
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
        info = await loop.run_in_executor(None, spotify_downloader.get_info_cached, resolved_url)

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


@router.callback_query(lambda c: c.data.startswith("sp_"))
async def callback_spotify(callback: types.CallbackQuery) -> None:
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
