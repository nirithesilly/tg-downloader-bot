from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader

class InstagramDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = self.default_opts.copy()
        self.ydl_opts['impersonate'] = 'chrome-120'
        self.ydl_opts['concurrent_fragments'] = 10
    
    def get_info(self, url: str) -> dict:
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                content_type = "photo"
                if info.get('duration', 0) > 0 or info.get('ext') in ['mp4', 'mov', 'avi']:
                    content_type = "video"
                
                formats = info.get('formats', [])
                for f in formats:
                    if f.get('vcodec') != 'none':
                        content_type = "video"
                        break
                
                return {
                    'title': info.get('title', 'instagram post')[:100],
                    'uploader': info.get('uploader', 'unknown'),
                    'description': info.get('description', '')[:200],
                    'duration': info.get('duration', 0),
                    'content_type': content_type,
                    'ext': info.get('ext', 'jpg'),
                }
        except Exception as e:
            raise Exception(f"ошибка получения информации instagram: {str(e)}")
    
    def download_video(self, url: str) -> str:
        try:
            opts = self.ydl_opts.copy()
            opts['format'] = 'best[ext=mp4]/best'
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except Exception as e:
            raise Exception(f"ошибка скачивания instagram: {str(e)}")
    
    def download_photo(self, url: str) -> str:
        try:
            opts = self.ydl_opts.copy()
            opts['format'] = 'best[ext=jpg]/best[ext=png]/best'
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except Exception as e:
            raise Exception(f"ошибка скачивания фото instagram: {str(e)}")
    
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
            raise Exception(f"ошибка скачивания аудио instagram: {str(e)}")
