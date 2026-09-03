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
    extract_url,
    generic_error,
    get_session,
    handle_too_large,
    safe_answer,
    send_media_split,
    store_session,
)

router = Router()
spotify_downloader = SpotifyDownloader()


@router.message(lambda msg: (extract_url(msg) and detect_service(extract_url(msg)) == "spotify"))
async def handle_spotify(message: types.Message) -> None:
    url = extract_url(message)
    if not url:
        return

    try:
        resolved_url = await asyncio.to_thread(spotify_downloader.resolve_url, url)

        if re.search(r'open\.spotify\.com/(?:album|playlist)/', resolved_url):
            await message.answer(
                "<b>поддерживаются только ссылки на отдельные треки spotify.</b>\n"
                "альбомы и плейлисты не поддерживаются — отправь ссылку на трек\n"
                "(open.spotify.com/track/...).",
                parse_mode="HTML"
            )
            return

        if re.search(r'open\.spotify\.com/(?:episode|show)/', resolved_url):
            await message.answer(
                "<b>подкасты не поддерживаются.</b>\n"
                "бот умеет скачивать только треки (open.spotify.com/track/...).",
                parse_mode="HTML"
            )
            return

        if not re.search(r'open\.spotify\.com/track/', resolved_url):
            await message.answer(
                "<b>поддерживаются только ссылки на треки spotify.</b>\n"
                "отправь ссылку вида open.spotify.com/track/...",
                parse_mode="HTML"
            )
            return

        info = await asyncio.to_thread(spotify_downloader.get_info_cached, resolved_url)
        sid = store_session(resolved_url, "spotify", message.from_user.id, info)

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
                    types.InlineKeyboardButton(text="скачать mp3", callback_data=f"sp_audio:{sid}")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("spotify", e), parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("sp_"))
async def callback_spotify(callback: types.CallbackQuery) -> None:
    await safe_answer(callback, "начинаю загрузку...")

    parts = callback.data.split(":", 1)
    action = parts[0]
    sid = parts[1] if len(parts) > 1 else callback.from_user.id

    data = get_session(sid)
    if not data or data.get("service") != "spotify":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    info = data.get("info") or {}
    title = info.get("title") or "Spotify Track"
    uploader = info.get("uploader") or info.get("artist") or "Spotify Artist"
    duration = info.get("duration")

    if action == "sp_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю трек из spotify (mp3)...",
                spotify_downloader.download_audio, url, "mp3",
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            caption = f"<b>{esc(title)}</b>\n{esc(uploader)}"
            await send_media_split(
                callback, filepath, "audio", caption,
                title=title, performer=uploader, duration=duration
            )
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("spotify", e), parse_mode="HTML")

