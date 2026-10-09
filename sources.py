"""Resolve supported sources without downloading audio."""
from dataclasses import dataclass
import re
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


def spotify_client(client_id=None):
    # Public metadata only. Never load cookies or start an interactive login.
    from SpotipyFree import Spotify
    return Spotify(login=False, getIsrc=False)


def spotify_tracks(client, kind, identifier):
    if kind == "track":
        track = client.track(identifier)
        return track["name"], [track]
    if kind == "album":
        album = client.album(identifier)
        page = client.album_tracks(identifier)
        title = album["name"]
    else:
        playlist = client.playlist(identifier)
        title = playlist["name"]
        page = client.playlist_items(identifier)
    tracks = []
    while page:
        for item in page.get("items", []):
            tracks.append((item.get("item") or item.get("track")) if kind == "playlist" else item)
        page = client.next(page) if page.get("next") else None
    return title, tracks


def resolve_spotify(url, emit, client_id):
    match = re.fullmatch(r"/(playlist|album|track)/([A-Za-z0-9]+)/*", urlparse(url).path)
    if not match:
        raise ValueError("Usa un enlace Spotify de playlist, álbum o canción.")
    emit("SPOTIFY // Leyendo lista pública sin llave; el audio vendrá de YouTube.")
    try:
        title, entries = spotify_tracks(spotify_client(client_id), *match.groups())
    except Exception as exc:
        status = getattr(exc, "http_status", None) or getattr(exc, "status_code", None)
        if status == 429:
            raise ValueError("Spotify limitó las solicitudes. Intenta más tarde.") from None
        raise ValueError("No se pudo leer Spotify público. Usa una canción, álbum o playlist pública. Las listas privadas requieren acceso autorizado; este modo no inicia sesión. Si la lista es pública, puede haber un cambio temporal del proveedor.") from None
    tracks, skipped = [], 0
    with yt_dlp.YoutubeDL(dict(quiet=True, extract_flat=True, socket_timeout=20, retries=3)) as ydl:
        for index, track in enumerate(entries, 1):
            if not track or track.get("is_local") or track.get("type", "track") != "track":
                skipped += 1
                continue
            artists = [a.get("name") or a.get("profile", {}).get("name", "") for a in track.get("artists", [])]
            original = ", ".join(a for a in artists if a) + " — " + track["name"]
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
