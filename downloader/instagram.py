import logging
from pathlib import Path
from typing import Optional

import yt_dlp

from downloader.base import BaseDownloader, FileTooLargeError
from utils.download_manager import DownloadCancelled

log = logging.getLogger(__name__)

MAX_RETRIES = 3


class InstagramDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.ydl_opts = self.default_opts.copy()
        self.ydl_opts.update(self.impersonate_opts())
        self.ydl_opts['concurrent_fragments'] = 10

    def get_info(self, url: str, **kwargs) -> dict:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
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
                last_err = e
                log.warning("instagram get_info attempt %d failed: %s", attempt + 1, e)
        raise Exception(f"ошибка получения информации instagram: {str(last_err)}")

    def download_video(self, url: str, max_size_mb: int = None, progress_hook=None,
                       cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'best[ext=mp4]/best'
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
                return self.safe_find_file(filename, Path(filename).stem)
        except FileTooLargeError:
            raise
        except Exception:
            self.cleanup_partial()
            raise

    def download_photo(self, url: str, max_size_mb: int = None, progress_hook=None,
                       cancel_check=None):
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'best[ext=jpg]/best[ext=png]/best'
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                entries = info.get('entries')
                if entries:
                    filenames = []
                    for entry in entries:
                        filename = ydl.prepare_filename(entry)
                        path = self.safe_find_file(filename, Path(filename).stem)
                        if Path(path).exists():
                            filenames.append(path)
                    if filenames:
                        return filenames
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except (FileTooLargeError, DownloadCancelled):
            raise
        except Exception:
            self.cleanup_partial()
            raise
