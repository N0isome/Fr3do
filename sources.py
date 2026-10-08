"""Resolve supported sources without downloading audio."""
from dataclasses import dataclass
import os
import re
import secrets
from urllib.parse import urlparse

import yt_dlp


@dataclass(frozen=True)
class Track:
    title: str
    url: str
    index: int
    original: str = ""


@dataclass
class Collection:
    title: str
    tracks: list[Track]
    playlist: bool
    spotify: bool = False
    skipped: int = 0


def platform(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower()
        for name, domains in {
            "youtube": ("youtube.com", "youtu.be"),
            "soundcloud": ("soundcloud.com",),
            "spotify": ("open.spotify.com",),
        }.items():
            if any(host == d or host.endswith("." + d) for d in domains):
                return name
    except ValueError:
        pass
    return None


def entry_url(entry, source):
    url = entry.get("webpage_url") or entry.get("url") or ""
    if platform(url) in {"youtube", "soundcloud"}:
        return url
    if source == "youtube" and re.fullmatch(r"[\w-]{11}", entry.get("id", "")):
        return "https://www.youtube.com/watch?v=" + entry["id"]
    return None


def resolve(url, emit=lambda message: None, client_id=None):
    source = platform(url)
    if not source:
        raise ValueError("Ingresa un enlace de YouTube, SoundCloud o Spotify.")
    if source == "spotify":
        return resolve_spotify(url, emit, client_id)
    options = dict(extract_flat="in_playlist", quiet=True, ignoreerrors=True,
                   socket_timeout=20, retries=3, noplaylist=False)
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("La fuente no está disponible o requiere iniciar sesión.")
    playlist = "entries" in info
    tracks, skipped = [], 0
    for index, entry in enumerate(info.get("entries", [info]), 1):
        link = entry_url(entry, source) if entry else None
        if not link or entry.get("availability") in {"private", "premium_only", "subscriber_only"}:
            skipped += 1
            continue
        tracks.append(Track(entry.get("title") or "audio", link, index))
    if not tracks:
        raise ValueError("No se encontraron pistas disponibles en esta fuente.")
    return Collection(info.get("title") or "Playlist", tracks, playlist, skipped=skipped)


def spotify_client(client_id):
    import spotipy
    from spotipy.cache_handler import MemoryCacheHandler
    from spotipy.oauth2 import SpotifyPKCE
    from spotipy.oauth2 import SpotifyOauthError, start_local_http_server
    client_id = client_id or os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise ValueError("Configura tu Client ID de Spotify para importar la lista.")
    # Tokens stay in memory; no secrets or token files enter the repository.
    class DesktopPKCE(SpotifyPKCE):
        def _get_auth_response_local_server(self, redirect_port):
            server = start_local_http_server(redirect_port)
            server.timeout = 120
            try:
                self._open_auth_url()
                server.handle_request()
                if not server.auth_code:
                    raise SpotifyOauthError("Autorización cancelada o sin respuesta después de 120 segundos.")
                if server.state != self.state:
                    raise SpotifyOauthError("La respuesta de autorización no coincide con esta sesión.")
                return server.auth_code
            finally:
                server.server_close()

    auth = DesktopPKCE(client_id=client_id, state=secrets.token_urlsafe(32),
                       redirect_uri="http://127.0.0.1:8888/callback",
                       scope="playlist-read-private playlist-read-collaborative",
                       cache_handler=MemoryCacheHandler(), open_browser=True)
    return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=2)


def spotify_tracks(client, kind, identifier):
    if kind == "track":
        track = client.track(identifier)
        return track["name"], [track]
    if kind == "album":
        album = client.album(identifier)
        page = album["tracks"]
        title = album["name"]
    else:
        playlist = client.playlist(identifier)
        title = playlist["name"]
        # /items is the current API; older Spotipy helpers may still use /tracks.
        page = client._get(f"playlists/{identifier}/items", limit=50)
    tracks = []
    while page:
        for item in page.get("items", []):
            tracks.append((item.get("item") or item.get("track")) if kind == "playlist" else item)
        page = client.next(page) if page.get("next") else None
    return title, tracks


def resolve_spotify(url, emit, client_id):
    import spotipy
    match = re.fullmatch(r"/(playlist|album|track)/([A-Za-z0-9]+)/*", urlparse(url).path)
    if not match:
        raise ValueError("Usa un enlace Spotify de playlist, álbum o canción.")
    emit("SPOTIFY // Autoriza el acceso en el navegador; el audio vendrá de YouTube.")
    try:
        title, entries = spotify_tracks(spotify_client(client_id), *match.groups())
    except spotipy.SpotifyException as exc:
        if exc.http_status == 403:
            raise ValueError("Spotify denegó el acceso. En modo desarrollo usa una playlist propia o colaborativa y verifica los usuarios autorizados de tu app.") from None
        if exc.http_status == 429:
            raise ValueError("Spotify limitó las solicitudes. Intenta más tarde.") from None
        raise ValueError("No se pudo leer Spotify. Revisa tu conexión y autorización.") from None
    tracks, skipped = [], 0
    with yt_dlp.YoutubeDL(dict(quiet=True, extract_flat=True, socket_timeout=20, retries=3)) as ydl:
        for index, track in enumerate(entries, 1):
            if not track or track.get("is_local") or track.get("type", "track") != "track":
                skipped += 1
                continue
            original = ", ".join(a["name"] for a in track.get("artists", [])) + " — " + track["name"]
            emit(f"MATCH // {index}/{len(entries)}: {original}")
            try:
                info = ydl.extract_info("ytsearch1:" + original + " official audio", download=False)
                candidate = next(iter((info or {}).get("entries") or []), None)
                link = entry_url(candidate, "youtube") if candidate else None
                if not link:
                    skipped += 1
                    continue
                tracks.append(Track(candidate.get("title") or original, link, index, original))
            except yt_dlp.utils.DownloadError:
                emit(f"MATCH // Sin coincidencia: {original}")
                skipped += 1
    if not tracks:
        raise ValueError("No se encontraron coincidencias descargables en YouTube.")
    return Collection(title, tracks, match[1] != "track", spotify=True, skipped=skipped)
