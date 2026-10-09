"""FR3DO Crystal desktop. Background work communicates through queued Qt signals."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QSettings, QUrl
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QIcon, QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QListWidget,
    QListWidgetItem, QFileDialog, QProgressBar, QPlainTextEdit, QMessageBox, QSizeGrip, QSizePolicy)
from sources import resolve, Collection
from downloads import DownloadEngine, clean_ansi
from native_glass import apply_glass

PALETTES = {'Rosa': '#F49ABA', 'Naranjo': '#FFAE78', 'Celeste': '#8ECFFF'}
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'

class Events(QObject):
    received = Signal(object)
    def put(self, event):
        self.received.emit(event)

class Header(QFrame):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(event)
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()

class AudioExtractorApp(QWidget):
    PAGE_SIZE = 50
    def __init__(self, persist=True):
        super().__init__()
        self.setWindowTitle('FR3DO · Crystal')
        self.setWindowIcon(QIcon(str(ASSETS / 'fr3do.svg')))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1120, 900)
        self.setMinimumSize(950, 860)
        self.settings = QSettings('FR3DO', 'Crystal') if persist else None
        self.palette_name = self.settings.value('palette', 'Rosa') if persist else 'Rosa'
        if self.palette_name not in PALETTES:
            self.palette_name = 'Rosa'
        self.glass_active = False
        self.busy = False
        self.collection = None
        self.selected = set()
        self.page = 0
        self.output_dir = Path.home() / 'Music' / 'FR3DO'
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fr3do')
        self.events = Events(self)
        self.events.received.connect(self._event, Qt.QueuedConnection)
        self.engine = DownloadEngine()
        self.engine.events = self.events
        self.engine.last_progress_emit = 0
        self._build()
        self._theme(self.palette_name)

    def _label(self, text, role=None):
        label = QLabel(text)
        if role: label.setObjectName(role)
        return label

    def _button(self, text, fn, primary=False):
        button = QPushButton(text)
        if primary: button.setObjectName('primary')
        button.clicked.connect(fn)
        return button

    def _card(self):
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        return card, layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 18, 30, 16)
        root.setSpacing(18)
        header = Header()
        header.setFixedHeight(54)
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ASSETS / 'fr3do.svg')).pixmap(40, 40))
        h.addWidget(mark)
        h.addWidget(self._label('FR3DO', 'brand'))
        h.addWidget(self._label('CRYSTAL / AUDIO STUDIO', 'eyebrow'))
        h.addStretch()
        for name, color in PALETTES.items():
            swatch = self._button('', lambda checked=False, n=name: self._theme(n))
            swatch.setFixedSize(24, 24)
            swatch.setStyleSheet(f'background:{color};border:3px solid #302c34;border-radius:12px;')
            swatch.setToolTip(name + ' + negro')
            swatch.setAccessibleName('Paleta ' + name)
            h.addWidget(swatch)
        self.glass = QCheckBox('Cristal')
        self.glass.setChecked(bool(self.settings.value('glass', True, type=bool)) if self.settings else True)
        self.glass.toggled.connect(self._update_glass)
        h.addWidget(self.glass)
        for text, fn in [('−', self.showMinimized), ('□', self._maximize), ('×', self.close)]:
            btn = self._button(text, fn)
            btn.setObjectName('windowControl')
            btn.setFixedSize(32, 32)
            h.addWidget(btn)
        root.addWidget(header)
        intro = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(6)
        words.addWidget(self._label('Tu música. A tu manera.', 'hero'))
        words.addWidget(self._label('Pega un enlace, elige las pistas y guarda tu audio.', 'muted'))
        intro.addLayout(words)
        intro.addStretch()
        self.theme_label = self._label('ROSA / NEGRO', 'eyebrow')
        intro.addWidget(self.theme_label, alignment=Qt.AlignBottom)
        root.addLayout(intro)
        source, layout = self._card()
        top = QHBoxLayout()
        top.addWidget(self._label('01  /  ORIGEN', 'eyebrow'))
        top.addStretch()
        top.addWidget(self._label('YouTube   ·   SoundCloud   ·   Spotify público', 'muted'))
        layout.addLayout(top)
        line = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText('Enlace de canción, álbum o playlist…')
        self.url.textChanged.connect(self._source_changed)
        self.url.returnPressed.connect(self._review)
        line.addWidget(self.url, 1)
        self.review_button = self._button('Revisar enlace  →', self._review, True)
        line.addWidget(self.review_button)
        layout.addLayout(line)
        root.addWidget(source)
        body = QHBoxLayout()
        body.setSpacing(18)
        left, layout = self._card()
        bar = QHBoxLayout()
        self.list_title = self._label('02  /  TUS PISTAS', 'eyebrow')
        bar.addWidget(self.list_title)
        bar.addStretch()
        self.counter = self._label('0 seleccionadas', 'muted')
        bar.addWidget(self.counter)
        layout.addLayout(bar)
        self.hint = self._label('Aquí aparecerán las canciones de tu enlace.', 'muted')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.tracks = QListWidget()
        self.tracks.setSpacing(6)
        self.tracks.setSelectionMode(QListWidget.NoSelection)
        self.tracks.itemChanged.connect(self._selection_changed)
        self.tracks.itemDoubleClicked.connect(self._open_track)
        self.tracks.setToolTip('Doble clic para escuchar la fuente antes de descargar.')
        layout.addWidget(self.tracks, 1)
        select = QHBoxLayout()
        self.all_button = self._button('Seleccionar todas', lambda: self._select_all(True))
        self.none_button = self._button('Limpiar', lambda: self._select_all(False))
        select.addWidget(self.all_button)
        select.addWidget(self.none_button)
        select.addStretch()
        self.previous = self._button('‹', lambda: self._change_page(-1))
        self.next = self._button('›', lambda: self._change_page(1))
        self.page_label = self._label('1 / 1', 'muted')
        select.addWidget(self.previous)
        select.addWidget(self.page_label)
        select.addWidget(self.next)
        layout.addLayout(select)
        body.addWidget(left, 1)
        right, layout = self._card()
        right.setFixedWidth(310)
        layout.setSpacing(10)
        layout.addWidget(self._label('03  /  EXPORTAR', 'eyebrow'))
        layout.addWidget(self._label('Listo para llevar.', 'subheading'))
        layout.addWidget(self._label('Formato de audio', 'muted'))
        self.format = QComboBox()
        self.format.addItems(['MP3', 'WAV', 'FLAC'])
        self.format.setMinimumHeight(44)
        layout.addWidget(self.format)
        layout.addWidget(self._label('Guardar en', 'muted'))
        self.destination = self._button('Música / FR3DO', self._folder)
        self.destination.setMinimumHeight(44)
        self.destination.setToolTip(str(self.output_dir))
        layout.addWidget(self.destination)
        self.stems = QCheckBox('Separar en 4 stems')
        stems_available = not getattr(sys, 'frozen', False) and importlib.util.find_spec('demucs') is not None
        self.stems.setEnabled(stems_available)
        self.stems.setToolTip('Voces, batería, bajo y otros. Instala requirements-stems.txt para activar.')
        layout.addWidget(self.stems)
        self.export_note = self._label('Las playlists se guardan en su propia carpeta, con un reporte de resultados.', 'muted')
        self.export_note.setWordWrap(True)
        layout.addWidget(self.export_note)
        layout.addStretch()
        self.download_button = self._button('Descargar selección  ↓', self._confirm_selection, True)
        self.download_button.setMinimumHeight(44)
        layout.addWidget(self.download_button)
        body.addWidget(right)
        root.addLayout(body, 1)
        footer, layout = self._card()
        layout.setContentsMargins(20, 14, 20, 14)
        row = QHBoxLayout()
        self.status = self._label('Todo listo. Agrega tu primer enlace.', 'muted')
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.status, 1)
        self.log_button = self._button('Ver actividad', self._toggle_log)
        row.addWidget(self.log_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(100)
        self.log.hide()
        layout.addWidget(self.log)
        root.addWidget(footer)
        bottom = QHBoxLayout()
        self.glass_note = self._label('FR3DO  /  PUBLIC LINKS · LOCAL FILES', 'eyebrow')
        bottom.addWidget(self.glass_note)
        bottom.addStretch()
        bottom.addWidget(QSizeGrip(self))
        root.addLayout(bottom)
        self._controls()

    def _theme(self, name):
        self.palette_name = name
        color = PALETTES[name]
        self.theme_label.setText(name.upper() + ' / NEGRO')
        self.setStyleSheet(f'''
            QWidget {{ color: #f4f0f5; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; }}
            QLabel {{ background: transparent; }}
            QLabel#brand {{ font-size: 29px; font-weight: 900; letter-spacing: 3px; }}
            QLabel#hero {{ font-size: 32px; font-weight: 700; }}
            QLabel#subheading {{ font-size: 24px; font-weight: 600; }}
            QLabel#eyebrow {{ font-size: 10px; letter-spacing: 2px; color: {color}; font-weight: 600; }}
            QLabel#muted {{ color: #b6b0bf; font-size: 12px; }}
            QFrame#card {{ background: rgba(22, 21, 29, 190); border: 1px solid rgba(255,255,255,26); border-radius: 22px; }}
            QPushButton, QComboBox, QLineEdit {{ background: rgba(255,255,255,9); border: 1px solid rgba(255,255,255,28); border-radius: 12px; padding: 12px 14px; }}
            QPushButton:hover {{ background: rgba(255,255,255,24); border-color: {color}; }}
            QPushButton#primary {{ background: {color}; color: #201923; font-weight: 700; border: none; }}
            QPushButton#primary:disabled {{ background:rgba(255,255,255,8);color:#686270; }}
            QPushButton#primary:hover {{ background: {QColor(color).lighter(112).name()}; }}
            QPushButton:disabled {{ background: rgba(255,255,255,8); color: #686270; border-color: rgba(255,255,255,12); }}
            QPushButton#windowControl {{ padding: 0; background: transparent; border:none; font-size: 19px; }}
            QLineEdit:focus {{ border-color: {color}; }}
            QComboBox QAbstractItemView {{ background: #26232e; selection-background-color: #514252; }}
            QComboBox::drop-down {{ border:0; width:25px; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ background: rgba(255,255,255,6); border: 1px solid rgba(255,255,255,12); border-radius: 12px; padding: 12px 10px; }}
            QListWidget::item:hover {{ background: rgba(255,255,255,14); }}
            QCheckBox {{ spacing: 8px; background:transparent; }}
            QCheckBox::indicator, QListWidget::indicator {{ width:16px; height:16px; border:1px solid #625b6d; border-radius:5px; background:transparent; }}
            QCheckBox::indicator:checked, QListWidget::indicator:checked {{ background:{color}; border-color:{color}; image:url({(ASSETS / 'check.svg').as_posix()}); }}
            QCheckBox:disabled {{color:#686270;}}
            QProgressBar {{ background:rgba(255,255,255,15);border:0;border-radius:2px; }}
            QProgressBar::chunk {{ background:{color};border-radius:2px; }}
            QPlainTextEdit {{background:rgba(0,0,0,40);border:0;border-radius:10px;color:#b6b0bf;font-size:11px;}}
            QScrollBar:vertical {{background:transparent;width:7px;margin:0;}}
            QScrollBar::handle:vertical {{background:#514a59;border-radius:3px;min-height:30px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        ''')
        if self.settings: self.settings.setValue('palette', name)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        accent = QColor(PALETTES[self.palette_name])
        accent.setAlpha(24 if self.glass_active else 255)
        if self.glass_active:
            gradient.setColorAt(0, accent)
            gradient.setColorAt(1, QColor(13, 14, 20, 90))
        else:
            gradient.setColorAt(0, QColor(PALETTES[self.palette_name]).darker(650))
            gradient.setColorAt(.55, QColor('#17151e'))
            gradient.setColorAt(1, QColor('#101218'))
        painter.setBrush(gradient)
        painter.setPen(QColor(255, 255, 255, 35))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 24, 24)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_glass()

    def _update_glass(self):
        try:
            self.glass_active = apply_glass(self, self.glass.isChecked())
        except (OSError, AttributeError):
            self.glass_active = False
        self.glass_note.setText('FR3DO / CRISTAL NATIVO' if self.glass_active else 'FR3DO / SUPERFICIE OSCURA')
        self.glass.setToolTip('Desenfoque nativo en Windows 10/11. En otros sistemas usa fondo oscuro.')
        if self.settings: self.settings.setValue('glass', self.glass.isChecked())
        self.update()

    def _maximize(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _toggle_log(self):
        self.log.setVisible(not self.log.isVisible())
        self.log_button.setText('Ocultar actividad' if self.log.isVisible() else 'Ver actividad')

    def _folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Guardar audio en', str(self.output_dir))
        if folder:
            self.output_dir = Path(folder)
            self.destination.setText(self.output_dir.name or str(self.output_dir))
            self.destination.setToolTip(str(self.output_dir))

    def _source_changed(self):
        self.collection = None
        self.selected.clear()
        self.tracks.clear()
        self.list_title.setText('02  /  TUS PISTAS')
        self.hint.setText('Revisa el nuevo enlace para ver sus canciones.')
        self._controls()

    def _review(self):
        if self.busy: return
        url = self.url.text().strip()
        if not url:
            self.status.setText('Pega un enlace para comenzar.')
            return
        self._set_busy(True)
        self.status.setText('Leyendo el enlace…')
        self.executor.submit(self._resolve_worker, url)

    def _resolve_worker(self, url):
        try:
            result = resolve(url, lambda message: self.events.put(('log', message)))
            self.events.put(('preview', result))
        except Exception as exc:
            self.events.put(('error', clean_ansi(exc)))

    def _show_preview(self, collection):
        self.collection = collection
        self.selected = set() if collection.spotify else set(range(len(collection.tracks)))
        self.page = 0
        self.list_title.setText('02  /  ' + collection.title[:40])
        text = 'Spotify: revisa las versiones de YouTube. Doble clic para escuchar; marca las que quieras.' if collection.spotify else 'Marca las pistas que quieres guardar. Doble clic para escuchar la fuente.'
        if collection.skipped: text += f' Se omitieron {collection.skipped} pistas no disponibles.'
        self.hint.setText(text)
        self._render_page()
        self.status.setText(f'{len(collection.tracks)} pistas listas para revisar.')

    def _render_page(self):
        self.tracks.blockSignals(True)
        self.tracks.clear()
        if self.collection:
            start = self.page * self.PAGE_SIZE
            for position in range(start, min(start + self.PAGE_SIZE, len(self.collection.tracks))):
                track = self.collection.tracks[position]
                text = f'{track.index:02d}   {track.title}'
                if track.original: text += '\n       Spotify: ' + track.original
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, position)
                item.setToolTip(text + '\nDoble clic para abrir la fuente de audio.')
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if position in self.selected else Qt.Unchecked)
                self.tracks.addItem(item)
        self.tracks.blockSignals(False)
        self._controls()

    def _selection_changed(self, item):
        pos = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked: self.selected.add(pos)
        else: self.selected.discard(pos)
        self._controls()

    def _select_all(self, selected):
        if not self.collection or self.busy: return
        self.selected = set(range(len(self.collection.tracks))) if selected else set()
        self._render_page()

    def _change_page(self, delta):
        if self.collection:
            self.page = max(0, min(self.page + delta, (len(self.collection.tracks)-1)//self.PAGE_SIZE))
            self._render_page()

    def _open_track(self, item):
        if self.collection:
            QDesktopServices.openUrl(QUrl(self.collection.tracks[item.data(Qt.UserRole)].url))

    def _controls(self):
        self.counter.setText(f'{len(self.selected)} seleccionadas')
        self.download_button.setEnabled(bool(self.collection and self.selected and not self.busy))
        self.review_button.setEnabled(not self.busy)
        self.url.setEnabled(not self.busy)
        self.tracks.setEnabled(not self.busy)
        for widget in (self.all_button, self.none_button, self.format, self.destination):
            widget.setEnabled(not self.busy)
        pages = max(1, (len(self.collection.tracks) + self.PAGE_SIZE - 1)//self.PAGE_SIZE) if self.collection else 1
        self.page_label.setText(f'{self.page+1} / {pages}')
        self.previous.setEnabled(not self.busy and self.page > 0)
        self.next.setEnabled(not self.busy and self.page+1 < pages)

    def _set_busy(self, busy):
        self.busy = busy
        self._controls()

    def _confirm_selection(self):
        if self.busy or not self.collection or not self.selected: return
        if not shutil.which('ffmpeg'):
            QMessageBox.warning(self, 'Falta FFmpeg', 'Instala FFmpeg y agrega su carpeta bin al PATH; luego reinicia FR3DO.')
            return
        try: self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, 'Carpeta no disponible', str(exc))
            return
        tracks = [self.collection.tracks[pos] for pos in sorted(self.selected)]
        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText('Preparando tu descarga…')
        self.executor.submit(self.engine._batch_worker, self.collection, tracks,
                             self.format.currentText().lower(), self.output_dir, self.stems.isChecked())

    def _event(self, event):
        kind, data = event
        if kind == 'log': self.log.appendPlainText(clean_ansi(data))
        elif kind == 'progress':
            value, stage, detail = data
            if value is not None: self.progress.setValue(int(value*1000))
            self.status.setText(detail)
        elif kind == 'preview':
            self._set_busy(False)
            self._show_preview(data)
        elif kind == 'error':
            self._set_busy(False)
            self.status.setText('No se pudo leer el enlace. Revisa la actividad.')
            self.log.appendPlainText(data)
            self.log.show()
            self.log_button.setText('Ocultar actividad')
        elif kind in ('success', 'partial', 'failure'):
            self._set_busy(False)
            message = f'Descarga lista · {data}' if kind == 'success' else (f'{data[0]}/{data[1]} descargadas. Revisa la actividad.' if kind == 'partial' else 'No se pudo completar la descarga. Revisa la actividad.')
            self.status.setText(message)

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, 'Proceso en curso', 'Espera a que termine el proceso antes de cerrar FR3DO.')
            event.ignore()
            return
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def launch():
    app = QApplication(sys.argv)
    app.setApplicationName('FR3DO')
    window = AudioExtractorApp()
    window.show()
    return app.exec()
