import asyncio

from aiogram import Router, types

from config import MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.facebook import FacebookDownloader
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
facebook_downloader = FacebookDownloader()


@router.message(lambda msg: msg.text and detect_service(msg.text) == "facebook")
async def handle_facebook(message: types.Message) -> None:
    url = message.text.strip()
    store_url(message.from_user.id, url, "facebook")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, facebook_downloader.get_info_cached, url)

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


@router.callback_query(lambda c: c.data.startswith("fb_"))
async def callback_facebook(callback: types.CallbackQuery) -> None:
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
