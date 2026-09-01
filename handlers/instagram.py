import asyncio

from aiogram import Router, types
from aiogram.types import FSInputFile

from config import MAX_FILE_SIZE_MB, MAX_DOWNLOAD_SIZE_MB
from downloader.base import FileTooLargeError
from downloader.instagram import InstagramDownloader
from handlers.utils import (
    detect_service,
    download_and_check,
    esc,
    generic_error,
    get_file_size_mb,
    handle_too_large,
    pop_url,
    run_download,
    safe_answer,
    store_url,
    too_large,
)
from utils.files import cleanup_temp_file

router = Router()
instagram_downloader = InstagramDownloader()


@router.message(lambda msg: msg.text and detect_service(msg.text) == "instagram")
async def handle_instagram(message: types.Message) -> None:
    url = message.text.strip()
    store_url(message.from_user.id, url, "instagram")

    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, instagram_downloader.get_info_cached, url)

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


@router.callback_query(lambda c: c.data.startswith("ig_"))
async def callback_instagram(callback: types.CallbackQuery) -> None:
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
