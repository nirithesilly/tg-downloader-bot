import asyncio
from pathlib import Path

from aiogram import Router, types
from aiogram.types import FSInputFile

from config import MAX_FILE_SIZE_MB, MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.instagram import InstagramDownloader
from handlers.utils import (
    chunk_list,
    detect_service,
    download_and_check,
    esc,
    extract_url,
    generic_error,
    get_file_size_mb,
    get_session,
    handle_too_large,
    run_download,
    safe_answer,
    send_media_split,
    store_session,
    too_large,
)
from utils.files import cleanup_temp_file

router = Router()
instagram_downloader = InstagramDownloader()


@router.message(lambda msg: (extract_url(msg) and detect_service(extract_url(msg)) == "instagram"))
async def handle_instagram(message: types.Message) -> None:
    url = extract_url(message)
    if not url:
        return

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, instagram_downloader.get_info_cached, url)

        sid = store_session(url, "instagram", message.from_user.id, info)
        content_type = info.get('content_type', 'photo')

        if content_type == "video":
            buttons = [
                [types.InlineKeyboardButton(text="видео/reels", callback_data=f"ig_video:{sid}")]
            ]
            type_label = "видео/reels"
        else:
            buttons = [
                [types.InlineKeyboardButton(text="скачать фото", callback_data=f"ig_photo:{sid}")]
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


@router.callback_query(lambda c: c.data.startswith("ig_"))
async def callback_instagram(callback: types.CallbackQuery) -> None:
    await safe_answer(callback, "начинаю загрузку...")

    parts = callback.data.split(":", 1)
    action = parts[0]
    sid = parts[1] if len(parts) > 1 else callback.from_user.id

    data = get_session(sid)
    if not data or data.get("service") != "instagram":
        await callback.message.edit_text("ссылка не найдена или устарела. отправьте ссылку заново.")
        return

    url = data["url"]
    info = data.get("info") or {}
    uploader = info.get("uploader") or "Instagram"

    if action == "ig_video":
        try:
            filepath, cancelled = await download_and_check(
                callback, "скачиваю видео/reels из instagram...",
                instagram_downloader.download_video, url,
                max_size_mb=MAX_DOWNLOAD_SIZE_MB
            )
            if cancelled:
                return
            caption = f"<b>видео из instagram скачано.</b>\nавтор: {esc(uploader)}"
            await send_media_split(callback, filepath, "video", caption, duration=info.get('duration'))
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
                try:
                    for chunk in chunk_list(result, 10):
                        media_items = []
                        for f in chunk:
                            ext = Path(f).suffix.lower()
                            if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                                media_items.append(types.InputMediaVideo(media=FSInputFile(f)))
                            else:
                                media_items.append(types.InputMediaPhoto(media=FSInputFile(f)))
                        if len(media_items) == 1:
                            if isinstance(media_items[0], types.InputMediaVideo):
                                await callback.message.answer_video(
                                    video=FSInputFile(chunk[0]),
                                    caption=f"<b>медиа из instagram:</b>\nавтор: {esc(uploader)}",
                                    parse_mode="HTML"
                                )
                            else:
                                await callback.message.answer_photo(
                                    photo=FSInputFile(chunk[0]),
                                    caption=f"<b>фото из instagram:</b>\nавтор: {esc(uploader)}",
                                    parse_mode="HTML"
                                )
                        else:
                            await callback.message.answer_media_group(media=media_items)
                finally:
                    for f in result:
                        cleanup_temp_file(f)
            else:
                try:
                    size_mb = get_file_size_mb(result)
                    if size_mb > MAX_FILE_SIZE_MB:
                        await too_large(callback, size_mb)
                        return
                    ext = Path(result).suffix.lower()
                    if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                        await callback.message.answer_video(
                            video=FSInputFile(result),
                            caption=f"<b>видео из instagram:</b>\nавтор: {esc(uploader)}",
                            parse_mode="HTML"
                        )
                    else:
                        await callback.message.answer_photo(
                            photo=FSInputFile(result),
                            caption=f"<b>фото из instagram:</b>\nавтор: {esc(uploader)}",
                            parse_mode="HTML"
                        )
                finally:
                    cleanup_temp_file(result)

            try:
                await callback.message.delete()
            except Exception:
                pass
        except FileTooLargeError as e:
            await handle_too_large(callback, e)
        except Exception as e:
            await callback.message.edit_text(generic_error("instagram", e), parse_mode="HTML")

