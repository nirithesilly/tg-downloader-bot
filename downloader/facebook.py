import urllib.request
from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader

class FacebookDownloader(BaseDownloader):
    def resolve_url(self, url: str) -> str:
        clean_url = url.replace("m.facebook.com", "www.facebook.com").replace("web.facebook.com", "www.facebook.com")
        try:
            req = urllib.request.Request(clean_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                resolved = resp.geturl()
                return resolved
        except Exception:
            return clean_url

    def get_info(self, url: str) -> dict:
        resolved = self.resolve_url(url)
        opts = self.default_opts.copy()
        opts['impersonate'] = 'chrome-120'
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved, download=False)
                return {
                    'title': info.get('title') or 'facebook video',
                    'uploader': info.get('uploader') or 'unknown',
                    'duration': info.get('duration', 0),
                    'id': info.get('id', 'fb_video')
                }
        except Exception as e:
            raise Exception(f"ошибка facebook: {str(e)}")

    def download_video(self, url: str, quality: str = "best") -> str:
        resolved = self.resolve_url(url)
        opts = self.default_opts.copy()
        opts['impersonate'] = 'chrome-120'
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        if quality == "720p":
            opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        elif quality == "480p":
            opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        else:
            opts['format'] = 'bestvideo+bestaudio/best'

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, info.get('id', ''))
        except Exception as e:
            raise Exception(f"ошибка скачивания facebook: {str(e)}")

    def download_audio(self, url: str, format: str = "mp3") -> str:
        resolved = self.resolve_url(url)
        opts = self.default_opts.copy()
        opts['impersonate'] = 'chrome-120'
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': format,
            'preferredquality': '192',
        }]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved, download=True)
                filename = ydl.prepare_filename(info)
                base = Path(filename).stem
                return str(Path(self.download_path) / f"{base}.{format}")
        except Exception as e:
            raise Exception(f"ошибка скачивания аудио facebook: {str(e)}")
