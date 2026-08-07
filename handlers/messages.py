from aiogram import Router, types

router = Router()


@router.message(lambda msg: msg.text and not msg.text.startswith(("http://", "https://")))
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
