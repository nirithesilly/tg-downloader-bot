import asyncio
import re
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from downloader.youtube import YouTubeDownloader
from downloader.tiktok import TikTokDownloader
from downloader.instagram import InstagramDownloader
from downloader.facebook import FacebookDownloader
from downloader.spotify import SpotifyDownloader
from config import MAX_FILE_SIZE_MB
from utils.files import cleanup_temp_file, get_file_size_mb

router = Router()
yt_downloader = YouTubeDownloader()
tiktok_downloader = TikTokDownloader()
instagram_downloader = InstagramDownloader()
facebook_downloader = FacebookDownloader()
spotify_downloader = SpotifyDownloader()

user_urls = {}

# --- КОМАНДА /start ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    name = message.from_user.first_name.lower()
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
        "@nirithesilly\n\n"
        "<b>исходный код:</b>\n"
        "https://github.com/nirithesilly/tg-downloader-bot",
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
        
        duration_min = info['duration'] // 60
        duration_sec = info['duration'] % 60
        
        title_str = str(info.get('title', '')).lower()[:100]
        uploader_str = str(info.get('uploader', '')).lower()
        
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
        await message.answer(
            f"<b>ошибка youtube:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
            parse_mode="HTML"
        )

# --- TIKTOK ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "tiktok")
async def handle_tiktok(message: types.Message):
    url = message.text.strip()
    user_urls[message.from_user.id] = {"url": url, "service": "tiktok"}
    
    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, tiktok_downloader.get_info, url)
        
        title_str = str(info.get('title', '')).lower()[:100]
        uploader_str = str(info.get('uploader', '')).lower()
        
        await message.answer(
            f"<b>tiktok найден.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>длительность:</b> {info['duration']} сек\n\n"
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
        await message.answer(
            f"<b>ошибка tiktok:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
            parse_mode="HTML"
        )

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
        
        title_str = str(info.get('title', '')).lower()
        uploader_str = str(info.get('uploader', '')).lower()
        desc_str = str(info.get('description', '')).lower()[:100]
        
        await message.answer(
            f"<b>instagram найден.</b>\n\n"
            f"<b>описание:</b> {title_str}\n"
            f"<b>автор:</b> {uploader_str}\n"
            f"<b>текст:</b> {desc_str}{'...' if len(info.get('description', '')) > 100 else ''}\n"
            f"<b>тип:</b> {type_label}\n\n"
            f"<b>выберите действие:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except Exception as e:
        await message.answer(
            f"<b>ошибка instagram:</b>\n{str(e)[:200].lower()}\n\n"
            f"если пост приватный - бот не сможет его скачать.\n"
            f"сообщи @nirithesilly",
            parse_mode="HTML"
        )

# --- FACEBOOK ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "facebook")
async def handle_facebook(message: types.Message):
    url = message.text.strip()
    user_urls[message.from_user.id] = {"url": url, "service": "facebook"}
    
    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, facebook_downloader.get_info, url)
        
        title_str = str(info.get('title', '')).lower()[:100]
        uploader_str = str(info.get('uploader', '')).lower()
        
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
        await message.answer(
            f"<b>ошибка facebook:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
            parse_mode="HTML"
        )

# --- SPOTIFY ---
@router.message(lambda msg: msg.text and detect_service(msg.text) == "spotify")
async def handle_spotify(message: types.Message):
    url = message.text.strip()
    user_urls[message.from_user.id] = {"url": url, "service": "spotify"}
    
    try:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, spotify_downloader.get_info, url)
        
        title_str = str(info.get('title', '')).lower()
        uploader_str = str(info.get('uploader', '')).lower()
        
        await message.answer(
            f"<b>spotify трек найден.</b>\n\n"
            f"<b>название:</b> {title_str}\n"
            f"<b>исполнитель:</b> {uploader_str}\n\n"
            f"<b>выберите действие:</b>",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="скачать mp3", callback_data="sp_audio")
                ]
            ])
        )
    except Exception as e:
        await message.answer(
            f"<b>ошибка spotify:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
            parse_mode="HTML"
        )

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
    
    if action == "yt_video":
        quality, label = "best", "лучшего качества"
    elif action == "yt_video_720":
        quality, label = "720p", "720p"
    elif action == "yt_video_480":
        quality, label = "480p", "480p"
    elif action == "yt_audio":
        await callback.message.edit_text("скачиваю аудио (mp3)...")
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, yt_downloader.download_audio, url, "mp3")
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(f"ошибка: {str(e)[:200].lower()}\n\nсообщи @nirithesilly")
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass
        return
    
    await callback.message.edit_text(f"скачиваю видео ({label})...")
    try:
        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, yt_downloader.download_video, url, quality)
        size_mb = get_file_size_mb(filepath)
        if size_mb > MAX_FILE_SIZE_MB:
            await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)\nпопробуйте меньшее качество (720p/480p).", parse_mode="HTML")
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
    except Exception as e:
        await callback.message.edit_text(f"ошибка: {str(e)[:200].lower()}\n\nсообщи @nirithesilly")
        try:
            if 'filepath' in locals():
                cleanup_temp_file(filepath)
        except:
            pass

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
    
    await callback.message.edit_text(
        "скачиваю видео из tiktok (без водяного знака)...",
        parse_mode="HTML"
    )
    
    if action == "tt_video":
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, tiktok_downloader.download_video, url)
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(
                f"<b>ошибка tiktok:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
                parse_mode="HTML"
            )
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass
    
    elif action == "tt_audio":
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, tiktok_downloader.download_audio, url, "mp3")
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(
                f"<b>ошибка tiktok:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly",
                parse_mode="HTML"
            )
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass

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
    
    if action == "ig_video":
        await callback.message.edit_text("скачиваю видео/reels из instagram...")
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, instagram_downloader.download_video, url)
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(f"<b>ошибка instagram:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly")
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass
    
    elif action == "ig_photo":
        await callback.message.edit_text("скачиваю фото из instagram...")
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, instagram_downloader.download_photo, url)
            photo = FSInputFile(filepath)
            await callback.message.answer_photo(
                photo=photo,
                caption="<b>фото из instagram скачано.</b>",
                parse_mode="HTML"
            )
            cleanup_temp_file(filepath)
            await callback.message.delete()
        except Exception as e:
            await callback.message.edit_text(f"<b>ошибка instagram:</b>\n{str(e)[:200].lower()}\n\nсообщи @nirithesilly")
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass

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
    
    if action == "fb_video":
        quality, label = "best", "лучшего качества"
    elif action == "fb_video_720":
        quality, label = "720p", "720p"
    elif action == "fb_video_480":
        quality, label = "480p", "480p"
    elif action == "fb_audio":
        await callback.message.edit_text("скачиваю аудио (mp3)...")
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, facebook_downloader.download_audio, url, "mp3")
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(f"ошибка: {str(e)[:200].lower()}\n\nсообщи @nirithesilly")
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass
        return
    
    await callback.message.edit_text(f"скачиваю видео facebook ({label})...")
    try:
        loop = asyncio.get_running_loop()
        filepath = await loop.run_in_executor(None, facebook_downloader.download_video, url, quality)
        size_mb = get_file_size_mb(filepath)
        if size_mb > MAX_FILE_SIZE_MB:
            await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
    except Exception as e:
        await callback.message.edit_text(f"ошибка: {str(e)[:200].lower()}\n\nсообщи @nirithesilly")
        try:
            if 'filepath' in locals():
                cleanup_temp_file(filepath)
        except:
            pass

# --- КОЛБЭКИ SPOTIFY ---
@router.callback_query(lambda c: c.data.startswith("sp_"))
async def callback_spotify(callback: types.CallbackQuery):
    await callback.answer("начинаю загрузку...")
    
    data = user_urls.get(callback.from_user.id)
    if not data or data.get("service") != "spotify":
        await callback.message.edit_text("ссылка не найдена. отправьте ссылку заново.")
        return
    
    url = data["url"]
    action = callback.data
    
    if action == "sp_audio":
        await callback.message.edit_text("скачиваю трек из spotify (mp3)...")
        try:
            loop = asyncio.get_running_loop()
            filepath = await loop.run_in_executor(None, spotify_downloader.download_audio, url, "mp3")
            size_mb = get_file_size_mb(filepath)
            if size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_text(f"<b>файл слишком большой.</b> ({size_mb:.1f} мб > лимита {MAX_FILE_SIZE_MB} мб)", parse_mode="HTML")
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
        except Exception as e:
            await callback.message.edit_text(f"ошибка: {str(e)[:200].lower()}\n\nсообщи @nirithesilly")
            try:
                if 'filepath' in locals():
                    cleanup_temp_file(filepath)
            except:
                pass
