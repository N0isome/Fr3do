from __future__ import annotations
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import yt_dlp

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def clean_ansi(value: object) -> str:
    return ANSI_RE.sub("", str(value)).strip()


class YTDLPLogger:
    """Deja en el log solo hitos; el progreso vive en la UI."""

    def __init__(self, emit):
        self.emit = emit

    def debug(self, message):
        if clean_ansi(message).startswith("[ExtractAudio]"):
            self.emit("STAGE // Conversión de audio iniciada.")

    def info(self, _message):
        pass

    def warning(self, message):
        self.emit(f"WARNING // {clean_ansi(message)}")

    def error(self, message):
        self.emit(f"ERROR // {clean_ansi(message)}")


class DownloadEngine:
    def _batch_worker(self, collection, tracks, output_format, output_dir, stems):
        try:
            target = output_dir
            if collection.playlist:
                target = self._unique_folder(output_dir, self._safe_name(collection.title))
                target.mkdir(parents=True)
            self.batch_total = len(tracks)
            results = []
            for position, track in enumerate(tracks):
                self.batch_position = position
                self.last_progress_emit = 0
                self._emit_log(f"TRACK // {position + 1}/{len(tracks)}: {track.title}")
                try:
                    path = self._download_track(track, output_format, target, stems)
                    results.append(dict(index=track.index, title=track.title,
                                        original=track.original, source=track.url,
                                        status="ok", output=str(path)))
                except Exception as exc:
                    self._emit_log(f"ERROR TRACK // {track.title}: {clean_ansi(exc)}")
                    results.append(dict(index=track.index, title=track.title,
                                        source=track.url, status="error", error=clean_ansi(exc)))
                self._emit_progress((position + 1) / len(tracks), "PLAYLIST", f"{position + 1}/{len(tracks)} PROCESADAS")
            report = self._unique_file(target, "fr3do-resultados.json")
            report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            ok = sum(item["status"] == "ok" for item in results)
            self._emit_log(f"RESULT // {ok} correctas; {len(tracks) - ok} fallidas. Reporte: {report}")
            if ok == len(tracks):
                self.events.put(("success", str(target)))
            elif ok:
                self.events.put(("partial", (ok, len(tracks), str(target))))
            else:
                self.events.put(("failure", None))
        except Exception as exc:
            self._emit_log(f"ERROR BATCH // {clean_ansi(exc)}")
            self.events.put(("failure", None))

    def _download_track(self, track, output_format, output_dir, stems):
        temp_dir = None
        try:
            self._emit_progress(self.batch_position / self.batch_total, "LINK ANALYSIS", "RESOLVIENDO FUENTE")
            temp_dir = Path(tempfile.mkdtemp(prefix="fr3do_", dir=output_dir))
            # Demucs recibe WAV aunque el selector muestre MP3. Así no depende
            # de backends opcionales para decodificar MP3 en Windows.
            processing_format = "wav" if stems else output_format
            processor = {"key": "FFmpegExtractAudio", "preferredcodec": processing_format}
            if processing_format == "mp3":
                processor["preferredquality"] = "320"
            options = {
                "format": "bestaudio/best",
                "outtmpl": str(temp_dir / f"{track.index:03d} - %(title).140B [%(id)s].%(ext)s"),
                "noplaylist": True, "windowsfilenames": True, "quiet": True,
                "no_warnings": True, "continuedl": True,
                "concurrent_fragment_downloads": 8,
                "buffersize": 1024 * 1024,
                "http_chunk_size": 10 * 1024 * 1024,
                "retries": 5,
                "fragment_retries": 5, "socket_timeout": 20,
                "logger": YTDLPLogger(self._emit_log),
                "progress_hooks": [self._download_progress],
                "postprocessors": [processor],
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(track.url, download=True)
                title = clean_ansi(info.get("title", "audio")) or "audio"
            files = [p for p in temp_dir.iterdir()
                     if p.is_file() and p.suffix.lower() == f".{processing_format}"]
            if not files:
                raise RuntimeError("No se encontró el audio convertido.")
            source = max(files, key=lambda p: p.stat().st_mtime)
            if stems:
                result = self._unique_folder(output_dir, f"{track.index:03d} - {self._safe_name(title)}")
                result.mkdir(parents=True)
                audio_path = result / source.name
            else:
                result = self._unique_file(output_dir, source.name)
                audio_path = result
            shutil.move(str(source), str(audio_path))
            self._emit_log(f"FILE // Audio guardado: {audio_path}")
            if stems:
                self._run_demucs(audio_path, result, temp_dir)
            return result
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _download_progress(self, data):
        if data.get("status") == "downloading":
            now = time.monotonic()
            if now - self.last_progress_emit < .08:
                return
            self.last_progress_emit = now
            done = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            value = min(done / total, 1) if total else .03
            speed = clean_ansi(data.get("_speed_str") or "CALCULANDO")
            eta = clean_ansi(data.get("_eta_str") or "--:--")
            self._emit_progress((self.batch_position + value * .9) / self.batch_total, "DOWNLOADING", f"{self.batch_position + 1}/{self.batch_total}  //  {speed}  //  ETA {eta}")
        elif data.get("status") == "finished":
            self._emit_progress(None, "TRANSCODING", "FFMPEG / AUDIO OUTPUT")
            self._emit_log("STAGE // Descarga completa; convirtiendo audio.")

    def _run_demucs(self, audio_path, song_folder, temp_dir):
        work = temp_dir / "demucs_output"
        self._emit_progress(None, "STEM SEPARATION", "HTDEMUCS / 04 CHANNEL")
        self._emit_log("STAGE // Separando voces, batería, bajo y otros.")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.run(
            [sys.executable, "-m", "demucs", "--name", "htdemucs",
             "--out", str(work), str(audio_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=flags)
        if process.returncode:
            lines = [line.strip() for line in clean_ansi(process.stdout).splitlines() if line.strip()]
            for line in lines[-8:]:
                self._emit_log(f"DEMUCS // {line}")
            raise RuntimeError(
                f"Demucs terminó con código {process.returncode}. Revisa el detalle anterior."
            )
        track_dirs = [p for p in work.rglob("*") if p.is_dir() and
                      all((p / f"{s}.wav").exists() for s in ("vocals", "drums", "bass", "other"))]
        if not track_dirs:
            raise RuntimeError("Demucs terminó sin generar los cuatro stems.")
        labels = {"vocals": "01 - Vocals.wav", "drums": "02 - Drums.wav",
                  "bass": "03 - Bass.wav", "other": "04 - Other.wav"}
        for stem, filename in labels.items():
            shutil.move(str(track_dirs[0] / f"{stem}.wav"), str(song_folder / filename))
        # El audio intermedio solo sirve como entrada de Demucs. En modo stems,
        # la carpeta final contiene exclusivamente las cuatro pistas separadas.
        audio_path.unlink(missing_ok=True)
        self._emit_log(f"FILE // Carpeta de stems lista: {song_folder}")

    @staticmethod
    def _safe_name(title):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
        return (re.sub(r"\s+", " ", name)[:120].rstrip(" .") or "audio")

    @staticmethod
    def _unique_folder(parent, name):
        path, number = parent / name, 2
        while path.exists():
            path, number = parent / f"{name} ({number})", number + 1
        return path

    @staticmethod
    def _unique_file(parent, name):
        path, number = parent / name, 2
        while path.exists():
            path, number = parent / f"{Path(name).stem} ({number}){Path(name).suffix}", number + 1
        return path

    def _emit_log(self, message):
        self.events.put(("log", clean_ansi(message)))

    def _emit_progress(self, value, stage, detail):
        self.events.put(("progress", (value, stage, detail)))

