import platform

from aiogram import Router, types
from aiogram.filters import Command

from handlers.facebook import router as facebook_router
from handlers.instagram import router as instagram_router
from handlers.spotify import router as spotify_router
from handlers.tiktok import router as tiktok_router
from handlers.youtube import router as youtube_router
from handlers.utils import detect_service, esc, extract_url, safe_answer
from utils.download_manager import download_manager

router = Router()
router.include_router(youtube_router)
router.include_router(tiktok_router)
router.include_router(instagram_router)
router.include_router(facebook_router)
router.include_router(spotify_router)


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
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


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
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
        "• файлы до 50 мб отправляются как есть\n"
        "• файлы больше 50 мб отправляются по частям (склей по инструкции)\n"
        "• файлы автоматически удаляются с сервера после отправки\n"
        "• приватные аккаунты instagram не поддерживаются\n\n"
        "<b>проблемы?</b> пиши @nirithesilly",
        parse_mode="HTML"
    )


@router.message(Command("about"))
async def cmd_about(message: types.Message) -> None:
    await message.answer(
        "<b>о боте</b>\n\n"
        "<b>название:</b> media downloader bot\n"
        "<b>версия:</b> 2.2.0\n"
        "<b>автор:</b> @nirithesilly\n\n"
        "<b>технологии:</b>\n"
        f"• python {platform.python_version()}\n"
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


@router.message(lambda msg: (extract_url(msg) is not None and detect_service(extract_url(msg)) == "unknown"))
async def handle_unknown(message: types.Message) -> None:

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


@router.callback_query(lambda c: c.data.startswith("cancel:"))
async def callback_cancel(callback: types.CallbackQuery) -> None:
    job_id = callback.data.split(":", 1)[1]
    found = download_manager.cancel(job_id)
    if found:
        await safe_answer(callback, "отменяю...")
    else:
        await safe_answer(callback, "загрузка уже завершена или отменена")
