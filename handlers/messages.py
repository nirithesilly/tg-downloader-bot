from aiogram import Router, types

from handlers.utils import extract_url

router = Router()


@router.message(lambda msg: extract_url(msg) is None)
async def handle_plain_text(message: types.Message):

    await message.answer(
        "это не ссылка.\n\n"
        "отправь мне ссылку на видео или трек из:\n"
        "• youtube\n"
        "• instagram\n"
        "• tiktok\n"
        "• facebook\n"
        "• spotify\n\n"
        "например: <code>https://youtube.com/watch?v=...</code>",
        parse_mode="HTML"
    )
