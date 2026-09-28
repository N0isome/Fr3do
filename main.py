from __future__ import annotations

import importlib.util
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk
import yt_dlp
from tkinter import filedialog

APP_NAME = "FR3DO // Consola de Extracción"
BG, PANEL, PANEL_2 = "#17140F", "#221D17", "#2B241C"
LINE, BEZEL, CREAM, CREAM_INK = "#060504", "#0D0B08", "#EFE6D3", "#2B2417"
RED, RED_DARK, RED_HOVER = "#E0603F", "#9C3521", "#C94B32"
AMBER, TEXT, MUTED, LED = "#DFA23A", "#EFE6D3", "#5B554C", "#57D96A"
DISPLAY_FONT, MONO_FONT = "Bahnschrift", "Cascadia Mono"
CHANNEL_COLORS = {
    "MASTER": "#C9C0AC", "VOCAL": "#E0603F", "DRUMS": "#DFA23A",
    "BASS": "#3FA48E", "OTHER": "#8F79D6",
}
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


class AudioExtractorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x790")
        self.minsize(980, 720)
        self.configure(fg_color=BG)
        ctk.set_appearance_mode("dark")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fr3do-worker")
        self.success_reset_id: str | None = None
        self.activity_job: str | None = None
        self.activity_step = 0
        self.progress_segments = []
        self.channel_meters: dict[str, list[ctk.CTkFrame]] = {}
        self.last_progress_emit = 0.0
        self.output_var = ctk.StringVar(value=str(Path.home() / "Downloads"))
        self.url_var = ctk.StringVar()
        self.format_var = ctk.StringVar(value="")
        self.stems_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="SYSTEM READY")
        self.progress_text_var = ctk.StringVar(value="00%")
        self.transfer_var = ctk.StringVar(value="EN ESPERA")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.after(100, self._process_events)

    def _build_ui(self):
        shell = ctk.CTkFrame(self, fg_color=PANEL, border_width=1, border_color=LINE, corner_radius=7)
        shell.pack(fill="both", expand=True, padx=26, pady=24)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(4, weight=1)
        self._header(shell)
        self._source(shell)
        self._progress(shell)
        self._channel_console(shell)
        self._monitor(shell)

    def _header(self, parent):
        frame = ctk.CTkFrame(parent, height=76, fg_color=BEZEL, corner_radius=6)
        frame.grid(row=0, column=0, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        power = ctk.CTkLabel(frame, text="", width=10, height=10, fg_color=LED, corner_radius=5)
        power.grid(row=0, column=0, rowspan=2, padx=(24, 12))
        ctk.CTkLabel(frame, text="FR3DO_", font=ctk.CTkFont(DISPLAY_FONT, 24, "bold"),
                     text_color=TEXT).grid(row=0, column=1, sticky="sw", pady=(13, 0))
        ctk.CTkLabel(frame, text="UNIDAD DE EXTRACCIÓN / MOTOR 4-STEM",
                     font=ctk.CTkFont(MONO_FONT, 10), text_color=MUTED).grid(
                         row=1, column=1, sticky="nw", pady=(0, 13))
        destination = ctk.CTkFrame(frame, fg_color="transparent")
        destination.grid(row=0, column=2, rowspan=2, sticky="e", padx=22, pady=17)
        destination.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(
            destination, textvariable=self.output_var, width=420, height=34,
            fg_color=CREAM, text_color=CREAM_INK, border_width=1,
            border_color="#000000", corner_radius=2, font=ctk.CTkFont(MONO_FONT, 11))
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        self.browse_button = ctk.CTkButton(
            destination, text="EXPLORAR", width=92, height=34, corner_radius=2,
            font=ctk.CTkFont(DISPLAY_FONT, 11, "bold"), fg_color=PANEL_2,
            hover_color="#3A3127", border_width=1, border_color="#000000",
            command=self._choose_folder)
        self.browse_button.grid(row=0, column=1)

    def _source(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        frame.grid(row=1, column=0, sticky="ew", padx=22, pady=(17, 8))
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="FUENTE", font=ctk.CTkFont(DISPLAY_FONT, 11, "bold"),
                     text_color=MUTED).grid(row=0, column=0, padx=(0, 12))
        self.url_entry = ctk.CTkEntry(
            frame, textvariable=self.url_var, height=39, fg_color=CREAM,
            text_color=CREAM_INK, placeholder_text="https://www.youtube.com/watch?v=...",
            placeholder_text_color="#746B5F", border_width=0, corner_radius=2,
            font=ctk.CTkFont(MONO_FONT, 11))
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.url_entry.bind("<Return>", lambda _event: self._start_download())
        self.format_selector = ctk.CTkSegmentedButton(
            frame, values=["WAV", "MP3 320"], variable=self.format_var,
            width=165, height=34, corner_radius=2, border_width=0,
            font=ctk.CTkFont(DISPLAY_FONT, 10, "bold"), fg_color=BEZEL,
            selected_color=AMBER, selected_hover_color="#F2B94A",
            unselected_color=BEZEL, unselected_hover_color="#312A21",
            text_color=CREAM_INK, text_color_disabled=MUTED)
        self.format_selector.grid(row=0, column=2, padx=(0, 12))
        self.stems_check = ctk.CTkSwitch(
            frame, text="4-STEM", variable=self.stems_var, width=90,
            font=ctk.CTkFont(DISPLAY_FONT, 10, "bold"), progress_color="#3FA48E",
            button_color=CREAM, button_hover_color="#FFFFFF", fg_color=BEZEL)
        self.stems_check.grid(row=0, column=3, padx=(0, 12))
        self.download_button = ctk.CTkButton(
            frame, text="●  EXTRAER", width=125, height=39, corner_radius=3,
            font=ctk.CTkFont(DISPLAY_FONT, 11, "bold"), fg_color=RED_DARK,
            hover_color=RED_HOVER, border_width=1, border_color="#5C1C10",
            command=self._start_download)
        self.download_button.grid(row=0, column=4)

    def _progress(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        frame.grid(row=2, column=0, sticky="ew", padx=22, pady=(7, 14))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, textvariable=self.status_var, font=ctk.CTkFont(DISPLAY_FONT, 10, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w", pady=(0, 7))
        ctk.CTkLabel(frame, textvariable=self.transfer_var, font=ctk.CTkFont(DISPLAY_FONT, 10),
                     text_color="#9A9186").grid(row=0, column=1, sticky="e", pady=(0, 7))
        ctk.CTkLabel(frame, textvariable=self.progress_text_var, width=50,
                     font=ctk.CTkFont(DISPLAY_FONT, 16, "bold"), text_color=LED).grid(
                         row=0, column=2, padx=(12, 0), pady=(0, 7))
        bar = ctk.CTkFrame(frame, height=18, fg_color=BEZEL, corner_radius=2)
        bar.grid(row=1, column=0, columnspan=3, sticky="ew")
        for i in range(40):
            bar.grid_columnconfigure(i, weight=1)
            segment = ctk.CTkFrame(bar, height=12, fg_color="#000000", corner_radius=1)
            segment.grid(row=0, column=i, sticky="ew", padx=1, pady=3)
            self.progress_segments.append(segment)

    def _channel_console(self, parent):
        console = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=0)
        console.grid(row=3, column=0, sticky="nsew")
        channels = [
            ("MASTER", "#C9C0AC", 82), ("VOCAL", "#E0603F", 70),
            ("DRUMS", "#DFA23A", 75), ("BASS", "#3FA48E", 68),
            ("OTHER", "#8F79D6", 60),
        ]
        for column, (name, color, level) in enumerate(channels):
            console.grid_columnconfigure(column, weight=1, uniform="channels")
            strip = ctk.CTkFrame(console, fg_color=PANEL_2, border_width=1,
                                 border_color="#0A0806", corner_radius=0)
            strip.grid(row=0, column=column, sticky="nsew")
            ctk.CTkFrame(strip, height=4, fg_color=color, corner_radius=0).pack(fill="x")
            ctk.CTkLabel(strip, text=name, font=ctk.CTkFont(DISPLAY_FONT, 12, "bold"),
                         text_color=TEXT).pack(pady=(9, 7))
            meter = ctk.CTkFrame(strip, width=28, height=92, fg_color=BEZEL, corner_radius=2)
            meter.pack()
            meter.pack_propagate(False)
            blocks = []
            for _ in range(10):
                block = ctk.CTkFrame(meter, height=6, fg_color="#241F18", corner_radius=1)
                block.pack(side="bottom", fill="x", padx=4, pady=1)
                blocks.append(block)
            self.channel_meters[name] = blocks
            slider = ctk.CTkSlider(
                strip, from_=0, to=100, orientation="vertical", height=105, width=18,
                fg_color=BEZEL, progress_color="#3A342A", button_color=color,
                button_hover_color=color, border_width=0)
            slider.set(level)
            slider.pack(pady=(10, 7))
            toggles = ctk.CTkFrame(strip, fg_color="transparent")
            toggles.pack(pady=(0, 9))
            for index, label in enumerate(("S", "M")):
                ctk.CTkButton(
                    toggles, text=label, width=27, height=21, corner_radius=2,
                    fg_color=PANEL, hover_color=color, border_width=1,
                    border_color="#000000", text_color=MUTED,
                    font=ctk.CTkFont(DISPLAY_FONT, 9, "bold")
                ).grid(row=0, column=index, padx=2)

    def _monitor(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        frame.grid(row=4, column=0, sticky="nsew", padx=22, pady=(13, 18))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="MONITOR DE EVENTOS",
                     font=ctk.CTkFont(DISPLAY_FONT, 10, "bold"), text_color=MUTED).grid(
                         row=0, column=0, sticky="w", pady=(0, 7))
        self.log_box = ctk.CTkTextbox(
            frame, height=80, fg_color=CREAM, text_color=CREAM_INK, border_width=0,
            corner_radius=2, wrap="word", font=ctk.CTkFont(MONO_FONT, 10))
        self.log_box.grid(row=1, column=0, sticky="nsew")
        self.log_box.configure(state="disabled")
        self._append_log("SYS // Selecciona formato, define destino e ingresa una URL.")

    def _choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    @staticmethod
    def _source_kind(value):
        try:
            parsed = urlparse(value.strip())
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in {"http", "https"}:
                return None
            if host == "youtu.be" or host.endswith("youtube.com"):
                return "youtube"
            if host == "soundcloud.com" or host.endswith(".soundcloud.com"):
                return "soundcloud"
        except ValueError:
            pass
        return None

    @classmethod
    def _valid_url(cls, value):
        return cls._source_kind(value) is not None

    def _start_download(self):
        if self.success_reset_id is not None:
            self.after_cancel(self.success_reset_id)
            self.success_reset_id = None
        url = self.url_var.get().strip()
        output_format = {"WAV": "wav", "MP3 320": "mp3"}.get(self.format_var.get())
        destination_text = self.output_var.get().strip()
        stems = self.stems_var.get()
        source_kind = self._source_kind(url)
        if source_kind is None:
            self._append_log("ERROR // URL inválida. Usa YouTube o SoundCloud.")
            return
        if output_format is None:
            self._append_log("ERROR // Selecciona WAV o MP3 320.")
            return
        if not destination_text:
            self._append_log("ERROR // Selecciona una carpeta de destino.")
            return
        if stems and importlib.util.find_spec("demucs") is None:
            self._append_log("ERROR // Demucs no está instalado en este entorno.")
            return
        output_dir = Path(destination_text).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            probe = output_dir / ".fr3do_write_test"
            probe.touch()
            probe.unlink()
        except OSError as exc:
            self._append_log(f"ERROR // No se puede escribir en el destino: {exc}")
            return
        if shutil.which("ffmpeg") is None:
            self._append_log("ERROR // FFmpeg no aparece en PATH.")
            return
        self._set_busy(True)
        self._set_progress(0, "LINK ANALYSIS", "INICIANDO")
        self._append_log(f"RUN // Nueva operación iniciada ({source_kind.upper()}).")
        self.executor.submit(self._worker, url, output_format, output_dir, stems)

    def _worker(self, url, output_format, output_dir, stems):
        temp_dir = None
        try:
            self._emit_progress(.02, "LINK ANALYSIS", "RESOLVIENDO FUENTE")
            temp_dir = Path(tempfile.mkdtemp(prefix="fr3do_", dir=output_dir))
            # Demucs recibe WAV aunque el selector muestre MP3. Así no depende
            # de backends opcionales para decodificar MP3 en Windows.
            processing_format = "wav" if stems else output_format
            processor = {"key": "FFmpegExtractAudio", "preferredcodec": processing_format}
            if processing_format == "mp3":
                processor["preferredquality"] = "320"
            options = {
                "format": "bestaudio/best",
                "outtmpl": str(temp_dir / "%(title).180B [%(id)s].%(ext)s"),
                "noplaylist": True, "windowsfilenames": True, "quiet": True,
                "no_warnings": True, "continuedl": True,
                "concurrent_fragment_downloads": 4,
                "buffersize": 1024 * 1024,
                "retries": 8,
                "fragment_retries": 5, "socket_timeout": 20,
                "logger": YTDLPLogger(self._emit_log),
                "progress_hooks": [self._download_progress],
                "postprocessors": [processor],
            }

            source_kind = self._source_kind(url)
            attempts = [("default", {})]
            if source_kind == "youtube":
                attempts.extend([
                    ("web_embedded/IPv4", {
                        "force_ipv4": True,
                        "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
                    }),
                    ("android/IPv4", {
                        "force_ipv4": True,
                        "extractor_args": {"youtube": {"player_client": ["android"]}},
                    }),
                ])

            last_error = None
            for attempt_name, overrides in attempts:
                attempt_options = dict(options)
                attempt_options.update(overrides)
                try:
                    if attempt_name != "default":
                        self._emit_log(f"RETRY // YouTube usando fallback {attempt_name}.")
                    with yt_dlp.YoutubeDL(attempt_options) as ydl:
                        info = ydl.extract_info(url, download=True)
                    title = clean_ansi(info.get("title", "audio")) or "audio"
                    last_error = None
                    break
                except yt_dlp.utils.DownloadError as exc:
                    last_error = exc
                    if source_kind != "youtube" or attempt_name == attempts[-1][0]:
                        raise
                    self._emit_log(
                        f"WARNING // Falló intento {attempt_name}: {clean_ansi(exc)}"
                    )
                    for partial in temp_dir.glob("*.part"):
                        partial.unlink(missing_ok=True)
            if last_error is not None:
                raise last_error
            files = [p for p in temp_dir.iterdir()
                     if p.is_file() and p.suffix.lower() == f".{processing_format}"]
            if not files:
                raise RuntimeError("No se encontró el audio convertido.")
            source = max(files, key=lambda p: p.stat().st_mtime)
            if stems:
                result = self._unique_folder(output_dir, self._safe_name(title))
                result.mkdir(parents=True)
                audio_path = result / source.name
            else:
                result = self._unique_file(output_dir, source.name)
                audio_path = result
            shutil.move(str(source), str(audio_path))
            self._emit_log(f"FILE // Audio guardado: {audio_path}")
            if stems:
                self._run_demucs(audio_path, result, temp_dir)
            self.events.put(("success", str(result)))
        except yt_dlp.utils.DownloadError as exc:
            self._emit_log(f"ERROR DOWNLOAD // {clean_ansi(exc)}")
            self.events.put(("failure", None))
        except Exception as exc:
            self._emit_log(f"ERROR // {clean_ansi(exc)}")
            self.events.put(("failure", None))
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
            self._emit_progress(value, "DOWNLOADING", f"{speed}  //  ETA {eta}")
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

    def _process_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(payload)
                elif event == "progress":
                    self._set_progress(*payload)
                elif event == "success":
                    self._set_progress(1, "PROCESS COMPLETE", "OUTPUT READY")
                    self._append_log(f"DONE // Salida disponible: {payload}")
                    self.url_var.set("")
                    self._set_busy(False)
                    self.download_button.configure(
                        text="SUCCESS  ✓", fg_color="#235C35", hover_color="#235C35"
                    )
                    self.success_reset_id = self.after(1600, self._reset_success_state)
                    self.url_entry.focus_set()
                elif event == "failure":
                    self._stop_activity()
                    for index, segment in enumerate(self.progress_segments):
                        segment.configure(fg_color=RED if index < 5 else "#000000")
                    self.status_var.set("PROCESS FAILED")
                    self.transfer_var.set("REVISA EVENT MONITOR")
                    self.progress_text_var.set("ERR")
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _set_progress(self, value, stage, detail):
        self.status_var.set(stage)
        self.transfer_var.set(detail)
        if value is None:
            if self.activity_job is None:
                self.activity_step = 0
                self._animate_activity()
            self.progress_text_var.set("•••")
        else:
            self._stop_activity()
            value = max(0, min(value, 1))
            lit = round(value * len(self.progress_segments))
            for index, segment in enumerate(self.progress_segments):
                if index < lit:
                    color = RED if index >= 34 else LED
                else:
                    color = "#000000"
                segment.configure(fg_color=color)
            master_lit = round(value * 10)
            for name, blocks in self.channel_meters.items():
                channel_lit = master_lit if name == "MASTER" else max(1, master_lit - 2)
                color = CHANNEL_COLORS[name]
                for index, block in enumerate(blocks):
                    block.configure(fg_color=color if index < channel_lit else "#241F18")
            self.progress_text_var.set(f"{round(value * 100):02d}%")

    def _animate_activity(self):
        """Animación de procesamiento para FFmpeg y Demucs sin simular porcentaje."""
        total = len(self.progress_segments)
        for index, segment in enumerate(self.progress_segments):
            distance = (index - self.activity_step) % total
            color = RED if distance == 7 else LED if distance < 7 else "#000000"
            segment.configure(fg_color=color)
        for channel_index, (name, blocks) in enumerate(self.channel_meters.items()):
            color = CHANNEL_COLORS[name]
            height = 3 + ((self.activity_step + channel_index * 2) % 7)
            for index, block in enumerate(blocks):
                block.configure(fg_color=color if index < height else "#241F18")
        self.activity_step = (self.activity_step + 1) % max(total, 1)
        self.activity_job = self.after(90, self._animate_activity)

    def _stop_activity(self):
        if self.activity_job is not None:
            self.after_cancel(self.activity_job)
            self.activity_job = None

    def _append_log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", clean_ansi(message) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.path_entry, self.browse_button, self.format_selector,
                       self.stems_check, self.url_entry):
            widget.configure(state=state)
        self.download_button.configure(state=state,
                                       text="●  PROCESANDO" if busy else "●  EXTRAER",
                                       fg_color=RED_DARK, hover_color=RED_HOVER)

    def _reset_success_state(self):
        """Deja la unidad lista sin borrar la carpeta elegida."""
        self.success_reset_id = None
        self._set_progress(0, "SYSTEM READY", "LAST EXPORT OK")
        self.download_button.configure(
            text="●  EXTRAER", fg_color=RED_DARK, hover_color=RED_HOVER
        )

    def _close_app(self):
        self._stop_activity()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == "__main__":
    AudioExtractorApp().mainloop()
