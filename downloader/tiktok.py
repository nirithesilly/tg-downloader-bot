import json
import urllib.request
import urllib.parse
from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader

class TikTokDownloader(BaseDownloader):
    def _fetch_tikwm_info(self, url: str) -> dict:
        resolved_url = self.resolve_url(url)
        api_url = "https://www.tikwm.com/api/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }
        data = urllib.parse.urlencode({'url': resolved_url, 'hd': 1}).encode('utf-8')
        req = urllib.request.Request(api_url, data=data, headers=headers)
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            if res_data.get('code') == 0:
                return res_data['data']
        raise Exception(f"tikwm api ответ: {res_data.get('msg', 'ошибка')}")

    def _download_file(self, file_url: str, output_path: Path) -> str:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        req = urllib.request.Request(file_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp, open(output_path, 'wb') as out_file:
            out_file.write(resp.read())
        return str(output_path)

    def get_info(self, url: str) -> dict:
        resolved_url = self.resolve_url(url)
        try:
            tikwm_data = self._fetch_tikwm_info(resolved_url)
            author = tikwm_data.get('author', {})
            return {
                'title': tikwm_data.get('title') or 'tiktok video',
                'uploader': author.get('nickname') or author.get('unique_id') or 'unknown',
                'duration': tikwm_data.get('duration', 0),
                'description': (tikwm_data.get('title') or '')[:200],
                'video_url': tikwm_data.get('hdplay') or tikwm_data.get('play'),
                'audio_url': tikwm_data.get('music'),
                'id': tikwm_data.get('id', 'tiktok_video')
            }
        except Exception:
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(resolved_url, download=False)
                    return {
                        'title': info.get('title', 'tiktok video'),
                        'uploader': info.get('uploader', 'unknown'),
                        'duration': info.get('duration', 0),
                        'description': info.get('description', '')[:200],
                        'id': info.get('id', 'tiktok_video')
                    }
            except Exception as ydl_err:
                raise Exception(f"ошибка получения видео tiktok: {ydl_err}")

    def download_video(self, url: str) -> str:
        try:
            info = self.get_info(url)
            video_direct_url = info.get('video_url')
            video_id = info.get('id', 'video')
            
            if video_direct_url:
                file_path = Path(self.download_path) / f"tiktok_{video_id}.mp4"
                return self._download_file(video_direct_url, file_path)
            
            resolved_url = self.resolve_url(url)
            opts = self.default_opts.copy()
            opts['format'] = 'best'
            with yt_dlp.YoutubeDL(opts) as ydl:
                y_info = ydl.extract_info(resolved_url, download=True)
                filename = ydl.prepare_filename(y_info)
                return self.safe_find_file(filename, Path(filename).stem)
        except Exception as e:
            raise Exception(f"ошибка скачивания tiktok видео: {str(e)}")

    def download_audio(self, url: str, format: str = "mp3") -> str:
        try:
            info = self.get_info(url)
            audio_direct_url = info.get('audio_url')
            video_id = info.get('id', 'audio')
            
            if audio_direct_url:
                file_path = Path(self.download_path) / f"tiktok_{video_id}.{format}"
                return self._download_file(audio_direct_url, file_path)
            
            resolved_url = self.resolve_url(url)
            opts = self.default_opts.copy()
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            with yt_dlp.YoutubeDL(opts) as ydl:
                y_info = ydl.extract_info(resolved_url, download=True)
                filename = ydl.prepare_filename(y_info)
                base = Path(filename).stem
                return str(Path(self.download_path) / f"{base}.{format}")
        except Exception as e:
            raise Exception(f"ошибка скачивания аудио tiktok: {str(e)}")
