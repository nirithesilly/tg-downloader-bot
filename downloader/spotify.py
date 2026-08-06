import json
import urllib.request
import urllib.parse
from pathlib import Path
import yt_dlp
from downloader.base import BaseDownloader

class SpotifyDownloader(BaseDownloader):
    def get_info(self, url: str) -> dict:
        """Получает названия трека и исполнителя через Spotify oEmbed API"""
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"
            req = urllib.request.Request(oembed_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                title = data.get('title', 'spotify track')
                author = data.get('author_name', 'unknown artist')
                thumbnail = data.get('thumbnail_url')
                return {
                    'title': title,
                    'uploader': author,
                    'query': f"{author} - {title} audio",
                    'thumbnail': thumbnail,
                    'duration': 0
                }
        except Exception:
            # Резервный разбор по ссылке
            track_id = url.split('/')[-1].split('?')[0]
            return {
                'title': 'spotify track',
                'uploader': 'spotify',
                'query': f"spotify track {track_id}",
                'thumbnail': None,
                'duration': 0
            }

    def download_audio(self, url: str, format: str = "mp3") -> str:
        info = self.get_info(url)
        search_query = f"ytsearch1:{info['query']}"

        opts = self.default_opts.copy()
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': format,
            'preferredquality': '192',
        }]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                search_info = ydl.extract_info(search_query, download=True)
                if 'entries' in search_info and len(search_info['entries']) > 0:
                    entry = search_info['entries'][0]
                    filename = ydl.prepare_filename(entry)
                    base = Path(filename).stem
                    return str(Path(self.download_path) / f"{base}.{format}")
                else:
                    raise Exception("трек не найден на youtube")
        except Exception as e:
            raise Exception(f"ошибка скачивания spotify: {str(e)}")
