import logging
from pathlib import Path
from typing import Optional

import yt_dlp

from downloader.base import BaseDownloader, FileTooLargeError
from utils.download_manager import DownloadCancelled

log = logging.getLogger(__name__)

MAX_RETRIES = 3


class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = self.default_opts.copy()
        self.ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        }

    def get_info(self, url: str, **kwargs) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                opts = self.ydl_opts.copy()
                opts['extract_flat'] = False
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return {
                        'id': info.get('id', ''),
                        'title': info.get('title', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', 'Unknown'),
                        'thumbnail': info.get('thumbnail', None),
                    }
            except Exception as e:
                last_err = e
                log.warning("youtube get_info attempt %d failed: %s", attempt + 1, e)
        raise Exception(f"ошибка получения информации: {str(last_err)}")

    def _video_format(self, quality: str) -> str:
        if quality == "720p":
            return ('bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]'
                    '/best[ext=mp4][height<=720]'
                    '/bestvideo[height<=720]+bestaudio/best[height<=720]')
        if quality == "480p":
            return ('bestvideo[ext=mp4][height<=480]+bestaudio[ext=m4a]'
                    '/best[ext=mp4][height<=480]'
                    '/bestvideo[height<=480]+bestaudio/best[height<=480]')
        return ('bestvideo[ext=mp4]+bestaudio[ext=m4a]'
                '/best[ext=mp4]'
                '/bestvideo+bestaudio/best')

    def download_video(self, url: str, quality: str = "best", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        outtmpl, stamp = self.make_outtmpl()
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = outtmpl
            opts['format'] = self._video_format(quality)
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]
            max_height = 720 if quality == "720p" else 480 if quality == "480p" else None

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                estimated = self._estimate_size(info, max_height)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, stamp)
        except (FileTooLargeError, DownloadCancelled):
            self.cleanup_stamp(stamp)
            raise
        except Exception:
            self.cleanup_stamp(stamp)
            raise

    def download_audio(self, url: str, format: str = "mp3", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        outtmpl, stamp = self.make_outtmpl()
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = outtmpl
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                estimated = self._estimate_size(info)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                base = Path(filename).stem
                candidate = str(Path(self.download_path) / f"{base}.{format}")
                return self.safe_find_file(candidate, stamp)
        except (FileTooLargeError, DownloadCancelled):
            self.cleanup_stamp(stamp)
            raise
        except Exception:
            self.cleanup_stamp(stamp)
            raise

