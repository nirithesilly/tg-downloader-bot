import asyncio

from aiogram import Router, types

from config import MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.facebook import FacebookDownloader
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
facebook_downloader = FacebookDownloader()


@router.message(lambda msg: (extract_url(msg) and detect_service(extract_url(msg)) == "facebook"))
async def handle_facebook(message: types.Message) -> None:
    url = extract_url(message)
    if not url:
        return

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, facebook_downloader.get_info_cached, url)

        sid = store_session(url, "facebook", message.from_user.id, info)
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
                    types.InlineKeyboardButton(text="видео (best)", callback_data=f"fb_video:{sid}"),
                    types.InlineKeyboardButton(text="аудио (mp3)", callback_data=f"fb_audio:{sid}")
                ],
                [
                    types.InlineKeyboardButton(text="720p", callback_data=f"fb_video_720:{sid}"),
                    types.InlineKeyboardButton(text="480p", callback_data=f"fb_video_480:{sid}")
                ]
            ])
        )
    except Exception as e:
        await message.answer(generic_error("facebook", e), parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("fb_"))
async def callback_facebook(callback: types.CallbackQuery) -> None:
    await safe_answer(callback, "начинаю загрузку...")

    parts = callback.data.split(":", 1)
    action = parts[0]
    sid = parts[1] if len(parts) > 1 else callback.from_user.id

    data = get_session(sid)
    if not data or data.get("service") != "facebook":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    info = data.get("info") or {}
    title = info.get("title") or "Facebook Video"
    uploader = info.get("uploader") or "Facebook"
    duration = info.get("duration")

    if action == "fb_audio":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю аудио (mp3)...",
                facebook_downloader.download_audio, url, "mp3",
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
        caption = f"<b>{esc(title)}</b>\n{esc(uploader)}"
        await send_media_split(callback, filepath, "video", caption, duration=duration)
    except FileTooLargeError as e:
        await handle_too_large(callback, e)
    except Exception as e:
        await callback.message.edit_text(generic_error("facebook", e), parse_mode="HTML")

