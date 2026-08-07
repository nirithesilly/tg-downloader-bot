from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader, FileTooLargeError

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
    
    def download_video(self, url: str, quality: str = "best", max_size_mb: int = None, progress_hook=None) -> str:
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            if quality == "720p":
                opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
                max_height = 720
            elif quality == "480p":
                opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
                max_height = 480
            else:
                opts['format'] = 'bestvideo+bestaudio/best'
                max_height = None

            if progress_hook:
                opts['progress_hooks'] = [progress_hook]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                estimated = self._estimate_size(info, max_height)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except FileTooLargeError:
            raise
        except Exception as e:
            raise Exception(f"ошибка скачивания видео: {str(e)}")

    def download_audio(self, url: str, format: str = "mp3", max_size_mb: int = None, progress_hook=None) -> str:
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            if progress_hook:
                opts['progress_hooks'] = [progress_hook]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                estimated = self._estimate_size(info)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                base = Path(filename).stem
                return str(Path(self.download_path) / f"{base}.{format}")
        except FileTooLargeError:
            raise
        except Exception as e:
            raise Exception(f"ошибка скачивания аудио: {str(e)}")
