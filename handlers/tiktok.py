import asyncio

from aiogram import Router, types
from aiogram.types import FSInputFile

from config import MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.tiktok import TikTokDownloader
from handlers.utils import (
    chunk_list,
    detect_service,
    download_and_check,
    esc,
    extract_url,
    generic_error,
    get_session,
    handle_too_large,
    run_download,
    safe_answer,
    send_media_split,
    store_session,
)
from utils.files import cleanup_temp_file

router = Router()
tiktok_downloader = TikTokDownloader()


@router.message(lambda msg: (extract_url(msg) and detect_service(extract_url(msg)) == "tiktok"))
async def handle_tiktok(message: types.Message) -> None:
    url = extract_url(message)
    if not url:
        return

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, tiktok_downloader.get_info_cached, url)

        sid = store_session(url, "tiktok", message.from_user.id, info)
        title_str = esc(str(info.get('title', '')).lower()[:100])
        uploader_str = esc(str(info.get('uploader', '')).lower())
        duration = info.get('duration') or 0
        content_type = info.get('content_type', 'video')
        images = info.get('images') or []

        if content_type == "photo" and images:
            buttons = [
                [
                    types.InlineKeyboardButton(text=f"скачать фото ({len(images)})", callback_data=f"tt_photo:{sid}"),
                    types.InlineKeyboardButton(text="аудио (mp3)", callback_data=f"tt_audio:{sid}")
                ]
            ]
            type_label = f"фото-слайдшоу ({len(images)} шт.)"
        else:
            buttons = [
                [
                    types.InlineKeyboardButton(text="видео (без водяного знака)", callback_data=f"tt_video:{sid}"),
                    types.InlineKeyboardButton(text="аудио (mp3)", callback_data=f"tt_audio:{sid}")
                ]
            ]
            type_label = f"видео ({duration} сек)" if duration else "видео"

        await message.answer(
            f"<b>tiktok найден.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>тип:</b> {type_label}\n\n"
            f"<b>выберите формат:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        await message.answer(generic_error("tiktok", e), parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("tt_"))
async def callback_tiktok(callback: types.CallbackQuery) -> None:
    await safe_answer(callback, "начинаю загрузку...")

    parts = callback.data.split(":", 1)
    action = parts[0]
    sid = parts[1] if len(parts) > 1 else callback.from_user.id

    data = get_session(sid)
    if not data or data.get("service") != "tiktok":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    info = data.get("info") or {}
    title = info.get("title") or "TikTok Media"
    uploader = info.get("uploader") or "TikTok"
    duration = info.get("duration")

    if action == "tt_video":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю видео из tiktok (без водяного знака)...",
                tiktok_downloader.download_video, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            caption = f"<b>{esc(title)}</b>\nавтор: {esc(uploader)} (без водяного знака)"
            await send_media_split(callback, filepath, "video", caption, duration=duration)
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")

    elif action == "tt_photo":
        try:
            paths, cancelled = await run_download(
                callback, "скачиваю фото из tiktok...",
                tiktok_downloader.download_photos, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            if not paths:
                raise Exception("фото не найдены")

            try:
                for chunk in chunk_list(paths, 10):
                    media_items = [types.InputMediaPhoto(media=FSInputFile(f)) for f in chunk]
                    if len(media_items) == 1:
                        await callback.message.answer_photo(
                            photo=FSInputFile(chunk[0]),
                            caption=f"<b>{esc(title)}</b>\nавтор: {esc(uploader)}",
                            parse_mode="HTML"
                        )
                    else:
                        await callback.message.answer_media_group(media=media_items)
            finally:
                for f in paths:
                    cleanup_temp_file(f)

            try:
                await callback.message.delete()
            except Exception:
                pass
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
            caption = f"<b>{esc(title)}</b>\nавтор: {esc(uploader)}"
            await send_media_split(
                callback, filepath, "audio", caption,
                title=title, performer=uploader, duration=duration
            )
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("tiktok", e), parse_mode="HTML")

