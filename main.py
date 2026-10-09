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
import json
import webbrowser

from sources import platform, resolve
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk
import yt_dlp
from tkinter import filedialog

APP_NAME = "Fr3do — Biblioteca de audio"
BG, PANEL, PANEL_2 = "#141816", "#1D2320", "#252D28"
LINE, BEZEL, CREAM, CREAM_INK = "#354039", "#101411", "#F0EEE4", "#202B24"
RED, RED_DARK, RED_HOVER = "#DDA57E", "#DDA57E", "#EDBB96"
AMBER, TEXT, MUTED, LED = "#DDA57E", "#F0EEE4", "#A6B3A9", "#8BBC9F"
DISPLAY_FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
MONO_FONT = DISPLAY_FONT
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
        self.geometry("1140x840")
        self.minsize(1000, 800)
        self.configure(fg_color=BG)
        ctk.set_appearance_mode("dark")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fr3do-worker")
        self.collection = None
        self.checks = []
        self.track_widgets = []
        self.analyzed_url = ""
        self.operation = "idle"
        self.log_visible = False
        self.saved_output = None
        self.last_progress_emit = 0.0
        self.busy = False
        self.batch_position = 0
        self.batch_total = 1
        self.spotify_client_id = os.environ.get("SPOTIPY_CLIENT_ID", "")
        self.output_var = ctk.StringVar(value=str(Path.home() / "Downloads"))
        self.url_var = ctk.StringVar()
        self.format_var = ctk.StringVar(value="MP3")
        self.stems_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Listo para empezar")
        self.transfer_var = ctk.StringVar(value="")

        self._build_ui()
        self.url_var.trace_add("write", self._source_changed)
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.event_job = self.after(150, self._process_events)

    def _font(self, size=14, bold=False):
        return ctk.CTkFont(DISPLAY_FONT, size, "bold" if bold else "normal")

    def _button(self, parent, text, command, primary=False, **kwargs):
        return ctk.CTkButton(
            parent, text=text, command=command, height=38, corner_radius=8,
            fg_color=AMBER if primary else PANEL_2,
            hover_color=RED_HOVER if primary else LINE,
            text_color=CREAM_INK if primary else TEXT,
            text_color_disabled="#68766C", font=self._font(13, True), **kwargs)

    def _build_ui(self):
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=30, pady=24)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 24))
        header.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkLabel(header, text="f", width=40, height=40,
                           corner_radius=12, fg_color=AMBER,
                           text_color=CREAM_INK, font=self._font(30, True))
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(header, text="fr3do", font=self._font(23, True),
                     text_color=TEXT).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text="TU BIBLIOTECA DE AUDIO", font=self._font(10),
                     text_color=MUTED).grid(row=1, column=1, sticky="w")
        self.spotify_button = self._button(header, "Conectar Spotify", self._configure_spotify, width=155)
        self.spotify_button.grid(row=0, column=2, rowspan=2)

        source = ctk.CTkFrame(shell, fg_color=PANEL, corner_radius=14)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        source.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(source, text="De un enlace a tu biblioteca.", font=self._font(25, True),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(source, text="Pega una canción o playlist. Revisa las pistas y elige cómo guardarlas.",
                     font=self._font(13), text_color=MUTED).grid(row=1, column=0, sticky="w", padx=22)
        ctk.CTkLabel(source, text="YouTube  /  SoundCloud  /  Spotify", font=self._font(11),
                     text_color=AMBER).grid(row=0, column=1, rowspan=2, sticky="e", padx=22)
        self.url_entry = ctk.CTkEntry(
            source, textvariable=self.url_var, height=46, fg_color=BEZEL,
            text_color=TEXT, border_color=LINE, border_width=1, corner_radius=8,
            placeholder_text="Pega el enlace aquí", placeholder_text_color=MUTED,
            font=self._font(14))
        self.url_entry.grid(row=2, column=0, sticky="ew", padx=(22, 12), pady=(16, 20))
        self.url_entry.bind("<Return>", lambda _event: self._start_download())
        self.review_button = self._button(source, "Revisar enlace", self._start_download,
                                          primary=True, width=155)
        self.review_button.grid(row=2, column=1, padx=(0, 22), pady=(16, 20))

        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=292)
        body.grid_rowconfigure(0, weight=1)
        library = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        library.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        library.grid_columnconfigure(0, weight=1)
        library.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(library, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(17, 2))
        top.grid_columnconfigure(0, weight=1)
        self.collection_label = ctk.CTkLabel(top, text="Tus pistas", anchor="w",
                                           font=self._font(19, True), text_color=TEXT)
        self.collection_label.grid(row=0, column=0, sticky="ew")
        self.count_label = ctk.CTkLabel(top, text="SIN ENLACE", font=self._font(10), text_color=MUTED)
        self.count_label.grid(row=0, column=1, padx=(12, 0))
        self.collection_note = ctk.CTkLabel(library, text="La selección aparecerá aquí.", anchor="w",
                                          justify="left", wraplength=550,
                                          font=self._font(12), text_color=MUTED)
        self.collection_note.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.track_area = ctk.CTkFrame(library, fg_color="transparent")
        self.track_area.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.track_area.grid_columnconfigure(0, weight=1)
        self.track_area.grid_rowconfigure(0, weight=1)
        self.selection_bar = ctk.CTkFrame(library, fg_color="transparent")
        self.selection_bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(2, 17))
        self.all_button = self._button(self.selection_bar, "Todas", lambda: self._select_all(True), width=80)
        self.all_button.pack(side="left", padx=(0, 8))
        self.none_button = self._button(self.selection_bar, "Ninguna", lambda: self._select_all(False), width=85)
        self.none_button.pack(side="left")
        self.selection_label = ctk.CTkLabel(self.selection_bar, text="", font=self._font(12), text_color=MUTED)
        self.selection_label.pack(side="right")
        self.previous_button = self._button(self.selection_bar, "‹", lambda: self._change_page(-1), width=30)
        self.next_button = self._button(self.selection_bar, "›", lambda: self._change_page(1), width=30)
        self.page_label = ctk.CTkLabel(self.selection_bar, text="", font=self._font(11), text_color=MUTED)
        self._empty_tracks()

        export = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14, width=292)
        export.grid(row=0, column=1, sticky="nsew")
        export.grid_columnconfigure(0, weight=1)
        export.grid_rowconfigure(8, weight=1)
        ctk.CTkLabel(export, text="Guardar audio", font=self._font(19, True),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 10))
        ctk.CTkLabel(export, text="FORMATO", font=self._font(10, True), text_color=MUTED).grid(
            row=1, column=0, sticky="w", padx=20, pady=(0, 8))
        self.format_selector = ctk.CTkSegmentedButton(
            export, values=["MP3", "WAV"], variable=self.format_var, height=38,
            font=self._font(13, True), fg_color=BEZEL,
            selected_color=AMBER, selected_hover_color=RED_HOVER,
            unselected_color=CREAM, unselected_hover_color="#D8DDCF",
            text_color=CREAM_INK, corner_radius=8,
            command=self._format_changed)
        self.format_selector.grid(row=2, column=0, sticky="ew", padx=20)
        self.format_note = ctk.CTkLabel(export, text="320 kbps · archivo compacto", font=self._font(11), text_color=MUTED)
        self.format_note.grid(row=3, column=0, sticky="w", padx=20, pady=(6, 12))
        ctk.CTkLabel(export, text="CARPETA DE DESTINO", font=self._font(10, True), text_color=MUTED).grid(
            row=4, column=0, sticky="w", padx=20, pady=(0, 8))
        self.path_entry = ctk.CTkEntry(export, textvariable=self.output_var, height=36,
                                      fg_color=BEZEL, text_color=TEXT, border_color=LINE,
                                      font=self._font(11), corner_radius=8)
        self.path_entry.grid(row=5, column=0, sticky="ew", padx=20)
        self.browse_button = self._button(export, "Cambiar carpeta", self._choose_folder, width=130)
        self.browse_button.grid(row=6, column=0, sticky="w", padx=20, pady=(6, 12))
        stems = ctk.CTkFrame(export, fg_color=PANEL_2, corner_radius=10)
        stems.grid(row=7, column=0, sticky="ew", padx=20)
        self.stems_check = ctk.CTkSwitch(stems, text="Separar instrumentos", variable=self.stems_var,
                                        font=self._font(12), text_color=TEXT, progress_color=AMBER,
                                        button_color=CREAM, button_hover_color=CREAM, fg_color=LINE,
                                        command=self._format_changed)
        self.stems_check.pack(anchor="w", padx=12, pady=(12, 5))
        ctk.CTkLabel(stems, text="Voz, batería, bajo y otros.\nRequiere más tiempo de procesamiento.",
                     justify="left", font=self._font(10), text_color=MUTED).pack(anchor="w", padx=12, pady=(0, 12))
        footer = ctk.CTkFrame(shell, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1)
        status_row = ctk.CTkFrame(footer, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=(0, 18))
        status_row.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(status_row, textvariable=self.status_var, anchor="w",
                                        font=self._font(12, True), text_color=MUTED)
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.details_button = self._button(status_row, "Ver actividad", self._toggle_log, width=120)
        self.details_button.grid(row=0, column=1)
        self.download_button = self._button(footer, "Descargar selección", self._confirm_selection, primary=True, width=292)
        self.download_button.grid(row=0, column=1, rowspan=3, sticky="nsew")
        self.progress_bar = ctk.CTkProgressBar(footer, height=4, fg_color=LINE, progress_color=AMBER)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=(0, 18), pady=(8, 0))
        self.progress_bar.set(0)
        self.detail_label = ctk.CTkLabel(footer, textvariable=self.transfer_var, anchor="w",
                                        font=self._font(10), text_color=MUTED)
        self.detail_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.log_box = ctk.CTkTextbox(shell, height=85, fg_color=BEZEL, text_color=MUTED,
                                     font=self._font(11), corner_radius=8, wrap="word")
        self.log_box.configure(state="disabled")
        self.log_box.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.log_box.grid_remove()
        self._set_busy(False)

    def _empty_tracks(self, message="Pega un enlace para empezar", detail="Revisa la lista antes de descargar.\nPuedes elegir todas las canciones o solo algunas."):
        for widget in self.track_area.winfo_children():
            widget.destroy()
        empty = ctk.CTkFrame(self.track_area, fg_color="transparent")
        empty.grid(row=0, column=0, sticky="nsew")
        empty.grid_columnconfigure(0, weight=1)
        empty.grid_rowconfigure(0, weight=1)
        empty.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(empty, text="♪", font=self._font(44), text_color=AMBER).grid(row=1, column=0, pady=(0, 10))
        ctk.CTkLabel(empty, text=message, font=self._font(17, True), text_color=TEXT).grid(row=2, column=0)
        ctk.CTkLabel(empty, text=detail, font=self._font(12), text_color=MUTED).grid(row=3, column=0, pady=(10, 0))
        self.all_button.configure(state="disabled")
        self.none_button.configure(state="disabled")
        for widget in (self.previous_button, self.page_label, self.next_button):
            widget.pack_forget()
        self.selection_label.configure(text="")

    def _toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_box.grid()
        else:
            self.log_box.grid_remove()
        self.details_button.configure(text="Ocultar actividad" if self.log_visible else "Ver actividad")

    def _format_changed(self, _value=None):
        self.format_note.configure(text="Cuatro pistas WAV por canción" if self.stems_var.get() else
                                  "320 kbps · archivo compacto" if self.format_var.get() == "MP3" else
                                  "Sin compresión · archivo más grande")
        self.format_selector.configure(state="disabled" if self.stems_var.get() or self.busy else "normal")

    def _source_changed(self, *_args):
        if self.collection and self.url_var.get().strip() != self.analyzed_url:
            self.collection = None
            self.checks = []
            self.track_widgets = []
            self.collection_label.configure(text="Tus pistas")
            self.count_label.configure(text="SIN REVISAR")
            self.collection_note.configure(text="Revisa el nuevo enlace para continuar.")
            self._empty_tracks()
            self.download_button.configure(state="disabled", text="Descargar selección")

    def _choose_folder(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    def _configure_spotify(self):
        dialog = ctk.CTkInputDialog(
            title="Conectar Spotify",
            text="Client ID de tu app Spotify (sin Client Secret).\n"
                 "Registra: http://127.0.0.1:8888/callback\n"
                 "En modo desarrollo: playlists propias o colaborativas.")
        value = dialog.get_input()
        if value and value.strip():
            self.spotify_client_id = value.strip()
            self._append_log("SPOTIFY // Client ID configurado para esta sesión.")

    @staticmethod
    def _valid_url(value):
        return platform(value) is not None

    def _start_download(self):
        if self.busy:
            return
        url = self.url_var.get().strip()
        if not self._valid_url(url):
            self._notice("Ingresa un enlace de YouTube, SoundCloud o Spotify.")
            return
        if platform(url) == "spotify" and not self.spotify_client_id:
            self._configure_spotify()
            if not self.spotify_client_id:
                self._notice("Conecta Spotify para revisar este enlace.")
                return
        self.collection = None
        self.checks = []
        self.track_widgets = []
        self.operation = "analysis"
        self.analyzed_url = url
        self._empty_tracks("Revisando tu enlace…", "Buscando las pistas disponibles.\nNo se descargará audio hasta que confirmes.")
        self.collection_label.configure(text="Tus pistas")
        self.count_label.configure(text="REVISANDO")
        self._set_busy(True)
        self._set_progress(None, "LINK ANALYSIS", "Esto puede tardar en playlists grandes.")
        self.executor.submit(self._analyze, url, None, None, None, self.spotify_client_id)

    def _notice(self, message):
        self.status_label.configure(text_color=AMBER)
        self.status_var.set(message)
        self._append_log(message)

    def _analyze(self, url, output_format, output_dir, stems, client_id):
        try:
            collection = resolve(url, self._emit_log, client_id)
            self.events.put(("preview", (collection, output_format, output_dir, stems)))
        except Exception as exc:
            self._emit_log(f"ERROR ANALYSIS // {clean_ansi(exc)}")
            self.events.put(("failure", None))

    def _show_preview(self, collection, output_format=None, output_dir=None, stems=None):
        self.collection = collection
        self.checks = []
        self.track_widgets = []
        for widget in self.track_area.winfo_children():
            widget.destroy()
        self.collection_label.configure(text=collection.title[:45])
        self.count_label.configure(text=f"{len(collection.tracks)} PISTAS")
        note = (platform(collection.tracks[0].url) or "Audio").capitalize() + " · Elige las canciones que quieres guardar."
        if collection.spotify:
            note = "Lista de Spotify · Audio de YouTube. Revisa cada versión antes de seleccionarla."
        if collection.skipped:
            note += f" {collection.skipped} entradas no disponibles."
        self.collection_note.configure(text=note)
        self.checks = [(ctk.BooleanVar(value=not collection.spotify), track) for track in collection.tracks]
        for var, _track in self.checks:
            var.trace_add("write", lambda *_: self._selection_changed())
        self.track_page = 0
        self._render_track_page()
        self.operation = "idle"
        self._set_busy(False)
        self._set_progress(0, "REVISAR SELECCIÓN", "")
        self._selection_changed()

    def _render_track_page(self):
        for widget in self.track_area.winfo_children():
            widget.destroy()
        self.track_widgets = []
        scroll = ctk.CTkScrollableFrame(self.track_area, fg_color="transparent", corner_radius=0,
                                        scrollbar_button_color=LINE, scrollbar_button_hover_color=MUTED)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        start = self.track_page * 50
        for number, (var, track) in enumerate(self.checks[start:start + 50]):
            row = ctk.CTkFrame(scroll, fg_color=PANEL_2, corner_radius=9)
            row.grid(row=number, column=0, sticky="ew", pady=(0, 6))
            row.grid_columnconfigure(2, weight=1)
            check = ctk.CTkCheckBox(row, text="", variable=var, width=26,
                                   checkbox_width=20, checkbox_height=20,
                                   fg_color=AMBER, hover_color=RED_HOVER,
                                   border_color="#68796C", checkmark_color=CREAM_INK,
                                   corner_radius=5, border_width=1)
            check.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=14)
            ctk.CTkLabel(row, text=f"{track.index:02d}", width=25, text_color=MUTED,
                         font=self._font(11)).grid(row=0, column=1, rowspan=2, padx=(0, 12))
            title = ctk.CTkLabel(row, text=track.original or track.title, anchor="w", justify="left",
                                 wraplength=340, height=22, text_color=TEXT, font=self._font(13, True))
            if track.original:
                title.grid(row=0, column=2, sticky="ew", pady=(10, 0))
                ctk.CTkLabel(row, text="YouTube: " + track.title, anchor="w", justify="left", wraplength=340,
                             height=16, text_color=MUTED, font=self._font(10)).grid(
                                 row=1, column=2, sticky="ew", pady=(0, 10))
            else:
                title.grid(row=0, column=2, rowspan=2, sticky="ew", pady=12)
            open_button = self._button(row, "Abrir", lambda link=track.url: webbrowser.open(link), width=56)
            open_button.grid(row=0, column=3, rowspan=2, padx=10)
            self.track_widgets.append(check)
        pages = (len(self.checks) + 49) // 50
        for widget in (self.previous_button, self.page_label, self.next_button):
            widget.pack_forget()
        if pages > 1:
            self.previous_button.pack(side="left", padx=(12, 4))
            self.page_label.pack(side="left", padx=4)
            self.next_button.pack(side="left", padx=4)
            self.page_label.configure(text=f"{self.track_page + 1} / {pages}")
            self.previous_button.configure(state="normal" if self.track_page else "disabled")
            self.next_button.configure(state="normal" if self.track_page < pages - 1 else "disabled")

    def _change_page(self, delta):
        if self.busy or not self.collection:
            return
        pages = (len(self.checks) + 49) // 50
        self.track_page = max(0, min(self.track_page + delta, pages - 1))
        self._render_track_page()

    def _select_all(self, value):
        if not self.busy:
            self._updating_selection = True
            try:
                for var, _track in self.checks:
                    var.set(value)
            finally:
                self._updating_selection = False
            self._selection_changed()

    def _selection_changed(self):
        if getattr(self, "_updating_selection", False):
            return
        count = sum(var.get() for var, _track in self.checks)
        self.selection_label.configure(text=f"{count} seleccionadas")
        self.download_button.configure(text=f"Descargar {count} pista{'s' if count != 1 else ''}" if count else "Selecciona pistas",
                                       state="normal" if count and not self.busy else "disabled")

    def _confirm_selection(self):
        if self.busy or not self.collection:
            return
        selected = [track for var, track in self.checks if var.get()]
        if not selected:
            self._notice("Selecciona al menos una pista.")
            return
        stems = self.stems_var.get()
        output_format = "wav" if self.format_var.get() == "WAV" else "mp3"
        destination_text = self.output_var.get().strip()
        if not destination_text:
            self._notice("Elige una carpeta de destino.")
            return
        if stems and importlib.util.find_spec("demucs") is None:
            self._notice("Instala Demucs para separar instrumentos.")
            return
        if shutil.which("ffmpeg") is None:
            self._notice("FFmpeg no está disponible. Revisa su instalación.")
            return
        output_dir = Path(destination_text).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=output_dir):
                pass
        except OSError:
            self._notice("No se puede escribir en esta carpeta. Elige otra.")
            return
        self.operation = "download"
        self._set_busy(True)
        self._set_progress(0, "DOWNLOADING", f"{len(selected)} pistas en la selección")
        self.executor.submit(self._batch_worker, self.collection, selected, output_format, output_dir, stems)

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

    def _process_events(self):
        # Bound each pass so a large queue cannot monopolize the UI thread.
        for _ in range(60):
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self._append_log(payload)
            elif event == "progress":
                self._set_progress(*payload)
            elif event == "preview":
                self._show_preview(*payload)
            elif event in {"success", "partial", "failure"}:
                self.operation = "idle"
                self._set_busy(False)
                if event == "success":
                    self.saved_output = payload
                    self._set_progress(1, "PROCESS COMPLETE", "Archivos guardados en la carpeta elegida.")
                    self._append_log(f"Salida disponible: {payload}")
                elif event == "partial":
                    ok, total, target = payload
                    self.saved_output = target
                    self._set_progress(1, "COMPLETADO CON ERRORES", f"{ok} de {total} pistas guardadas. Consulta la actividad.")
                else:
                    self._set_progress(0, "PROCESS FAILED", "Revisa el detalle en actividad.")
        self.event_job = self.after(150, self._process_events)

    def _set_progress(self, value, stage, detail):
        labels = {
            "LINK ANALYSIS": "Revisando enlace",
            "REVISAR SELECCIÓN": "Lista para descargar",
            "DOWNLOADING": "Descargando audio",
            "TRANSCODING": "Convirtiendo audio",
            "STEM SEPARATION": "Separando instrumentos",
            "PLAYLIST": "Procesando selección",
            "PROCESS COMPLETE": "Descarga completa",
            "COMPLETADO CON ERRORES": "Descarga completada con errores",
            "PROCESS FAILED": "No se pudo completar",
            "SYSTEM READY": "Listo para empezar",
        }
        self.status_label.configure(text_color=LED if stage == "PROCESS COMPLETE" else
                                    AMBER if stage in {"PROCESS FAILED", "COMPLETADO CON ERRORES"} else MUTED)
        self.status_var.set(labels.get(stage, stage))
        self.transfer_var.set(detail)
        # Keep the last known percentage during FFmpeg/Demucs; no animation loop.
        if value is not None:
            self.progress_bar.set(max(0, min(value, 1)))

    def _append_log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", clean_ansi(message) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.path_entry, self.browse_button, self.stems_check,
                       self.url_entry, self.spotify_button, self.review_button):
            widget.configure(state=state)
        for widget in self.track_widgets:
            widget.configure(state=state)
        self.all_button.configure(state="normal" if self.collection and not busy else "disabled")
        self.none_button.configure(state="normal" if self.collection and not busy else "disabled")
        self.review_button.configure(text="Revisando…" if busy and self.operation == "analysis" else "Revisar enlace")
        if self.collection and len(self.checks) > 50:
            pages = (len(self.checks) + 49) // 50
            self.previous_button.configure(state="normal" if not busy and self.track_page else "disabled")
            self.next_button.configure(state="normal" if not busy and self.track_page < pages - 1 else "disabled")
        self._format_changed()
        self._selection_changed()
        if busy:
            self.download_button.configure(text="Descargando…" if self.operation == "download" else "Revisando enlace…")

    def _close_app(self):
        self.after_cancel(self.event_job)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == "__main__":
    AudioExtractorApp().mainloop()

