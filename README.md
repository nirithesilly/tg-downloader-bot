# tg-downloader-bot

a telegram bot that downloads media from youtube, instagram, tiktok, facebook and spotify. it's my first real project, be gentle

## what it can do

youtube: video (best/720p/480p) or mp3

instagram: video/reels or photo

tiktok: video (no watermark!!) or mp3

facebook: video (best / 720p / 480p) or mp3

spotify: single tracks as mp3 (albums/playlists/podcasts = no, sorry)

## how it handles big files...

telegram has this dumb 50mb limit, right?

so instead of just erroring out - the bot splits the file into 45mb parts and sends them all to you, plus a little note on how to glue them back together (cat/copy/b stuff)... i didnt really test it, it might just not work.

hopefully that's useful. i mean. it seemed useful at the time.

## other stuff it does

queue + concurrency limit (so it doesn't die when 10 people send links at once)
you can cancel a download mid-way (it cleans up after itself)
anti-spam throttle middleware (1.5s between messages, sorry not sorry)
auto-deletes files from the server after sending (privacy-ish)
periodic cleanup of old files (nothing lives on the server forever)

## what it does NOT do

private instagram accounts
youtube playlists (single videos only, sorry)
spotify albums/playlists / podcasts (track links only)
hosting... yeah it's not deployed anywhere. it's just code. for now.

## how to run it

honestly, it's simple:

1. git clone nirithesilly/tg-downloader-bot
   cd tg-downloader-bot

2. create a venv. python -m venv .venv
   source .venv/bin/activate

3. install deps
   pip install -r requirements.txt

4. add your token
   copy .env.example to .env (or just create .env) and put BOT_TOKEN=123456:your-bot-token-here (get it from @BotFather)

5. run
   python bot.py

there's also a Dockerfile if you're into that

## stack

- python 3.13
- aiogram 3 (async telegram framework)
- yt-dlp (the actual downloader engine)
- curl_cffi (impersonates chrome so youtube/etc don't hate us)
- ffmpeg (for audio extraction - required, make sure it's installed)

## known issues / todos

- some sites (instagram mainly) change their html often, so the downloader breaks from time to time... it's a whack-a-mole thing
- no tests yet (i know, i know...)
- no error-retry logic on spotify sometimes
- cleanup could be smarter

## the end.

if you found this useful - cool.
if you have advice/feedback/want to point out how terrible my code is - please do, that's literally why it's public.

issues and PRs welcome.
