from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = self.default_opts.copy()
        self.ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash'],
            }
        }
    
    def get_info(self, url: str) -> dict:
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'thumbnail': info.get('thumbnail', None),
                }
        except Exception as e:
            raise Exception(f"ошибка получения информации: {str(e)}")
    
    def download_video(self, url: str, quality: str = "best") -> str:
        try:
            opts = self.ydl_opts.copy()
            if quality == "720p":
                opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
            elif quality == "480p":
                opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
            else:
                opts['format'] = 'bestvideo+bestaudio/best'
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except Exception as e:
            raise Exception(f"ошибка скачивания видео: {str(e)}")
    
    def download_audio(self, url: str, format: str = "mp3") -> str:
        try:
            opts = self.ydl_opts.copy()
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base = Path(filename).stem
                return str(Path(self.download_path) / f"{base}.{format}")
        except Exception as e:
            raise Exception(f"ошибка скачивания аудио: {str(e)}")
