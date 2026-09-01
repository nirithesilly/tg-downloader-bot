import asyncio

from aiogram import Router, types

from config import MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.tiktok import TikTokDownloader
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
tiktok_downloader = TikTokDownloader()


@router.message(lambda msg: msg.text and detect_service(msg.text) == "tiktok")
async def handle_tiktok(message: types.Message) -> None:
    url = message.text.strip()
    store_url(message.from_user.id, url, "tiktok")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, tiktok_downloader.get_info_cached, url)

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


@router.callback_query(lambda c: c.data.startswith("tt_"))
async def callback_tiktok(callback: types.CallbackQuery) -> None:
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
