import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from desktop import AudioExtractorApp, PALETTES
from sources import Collection, Track

APP = QApplication.instance() or QApplication([])

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.window = AudioExtractorApp(persist=False)
        self.window.show()
        APP.processEvents()
        self.window.url.setText('https://youtube.com/playlist?list=demo')

    def tearDown(self):
        self.window._set_busy(False)
        self.window.close()
        APP.processEvents()

    def load(self, count=3, spotify=False):
        tracks = [Track(f'Song {i}', 'https://youtu.be/abcdefghijk', i,
                        'Spotify song' if spotify else '') for i in range(1, count+1)]
        self.window._show_preview(Collection('Demo', tracks, True, spotify))
        APP.processEvents()

    def test_selection_and_busy_controls(self):
        self.load()
        self.window._select_all(False)
        self.assertFalse(self.window.download_button.isEnabled())
        self.window._select_all(True)
        self.assertTrue(self.window.download_button.isEnabled())
        self.window._set_busy(True)
        self.assertFalse(self.window.review_button.isEnabled())
        self.assertFalse(self.window.download_button.isEnabled())
        self.assertFalse(self.window.url.isEnabled())

    def test_page_selection_persists_and_spotify_requires_review(self):
        self.load(55, True)
        self.assertEqual(self.window.selected, set())
        self.assertEqual(self.window.tracks.count(), 50)
        self.window.tracks.item(0).setCheckState(Qt.Checked)
        self.window._change_page(1)
        self.assertEqual(self.window.tracks.count(), 5)
        self.window.tracks.item(2).setCheckState(Qt.Checked)
        self.window._change_page(-1)
        self.assertEqual(self.window.selected, {0,52})
        self.assertEqual(self.window.tracks.item(0).checkState(), Qt.Checked)

    def test_editing_source_invalidates_selection(self):
        self.load()
        self.window.url.setText('https://soundcloud.com/artist/new-song')
        self.assertIsNone(self.window.collection)
        self.assertFalse(self.window.download_button.isEnabled())

    def test_download_uses_current_options(self):
        self.load()
        self.window.tracks.item(1).setCheckState(Qt.Unchecked)
        self.window.format.setCurrentText('WAV')
        with tempfile.TemporaryDirectory() as folder:
            self.window.output_dir = Path(folder)
            with patch('desktop.shutil.which', return_value='ffmpeg'), patch.object(self.window.executor,'submit') as submit:
                self.window._confirm_selection()
                args = submit.call_args.args
                self.assertEqual([t.index for t in args[2]], [1,3])
                self.assertEqual(args[3], 'wav')
                self.assertEqual(args[4], Path(folder))
                self.assertFalse(args[5])

    def test_palettes_and_minimum_size_do_not_clip_export(self):
        self.load()
        self.window.resize(950, 860)
        for name in PALETTES:
            self.window._theme(name)
            APP.processEvents()
            self.assertEqual(self.window.palette_name, name)
            for widget in (self.window.format, self.window.destination, self.window.download_button):
                self.assertGreaterEqual(widget.height(), 44)
                self.assertGreater(widget.width(), 200)
            self.assertTrue(self.window.download_button.isVisible())

    def test_worker_events_update_ui_and_release_controls(self):
        self.window._set_busy(True)
        self.window.events.put(('error','Public provider unavailable'))
        APP.processEvents()
        self.assertFalse(self.window.busy)
        self.assertIn('Public provider unavailable', self.window.log.toPlainText())
        self.assertTrue(self.window.log.isVisible())

if __name__ == '__main__': unittest.main()
