"""Run UI checks on a desktop or under a virtual X display."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import AudioExtractorApp
from sources import Collection, Track


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Requires a desktop display")
class FlowTests(unittest.TestCase):
    def setUp(self):
        self.app = AudioExtractorApp()
        self.app.update()
        self.app.url_var.set("https://youtube.com/playlist?list=demo")
        self.app.analyzed_url = self.app.url_var.get()

    def tearDown(self):
        # Dispose third-party toolkit timers when tests create multiple Tk roots.
        for identifier in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", identifier)
        self.app._close_app()

    def load(self, count=3, spotify=False):
        tracks = [Track(f"Song {i}", "https://youtu.be/abcdefghijk", i,
                        "Spotify song" if spotify else "") for i in range(1, count + 1)]
        self.app._show_preview(Collection("Demo", tracks, True, spotify))
        self.app.update()

    def test_selection_and_busy_controls(self):
        self.load()
        self.app._select_all(False)
        self.assertEqual(self.app.download_button.cget("state"), "disabled")
        self.app._select_all(True)
        self.assertEqual(self.app.download_button.cget("state"), "normal")
        self.app._set_busy(True)
        self.assertEqual(self.app.review_button.cget("state"), "disabled")
        self.assertEqual(self.app.download_button.cget("state"), "disabled")

    def test_page_selection_persists_and_spotify_requires_review(self):
        self.load(55, spotify=True)
        self.assertEqual(sum(v.get() for v, _ in self.app.checks), 0)
        self.assertEqual(len(self.app.track_widgets), 50)
        self.app.checks[0][0].set(True)
        self.app._change_page(1)
        self.assertEqual(len(self.app.track_widgets), 5)
        self.app.checks[52][0].set(True)
        self.app._change_page(-1)
        self.assertTrue(self.app.checks[0][0].get())
        self.assertEqual(sum(v.get() for v, _ in self.app.checks), 2)

    def test_editing_source_invalidates_old_selection(self):
        self.load()
        self.app.url_var.set("https://soundcloud.com/artist/new-song")
        self.assertIsNone(self.app.collection)
        self.assertEqual(self.app.download_button.cget("state"), "disabled")

    def test_confirmation_reads_current_export_options(self):
        self.load()
        self.app.checks[1][0].set(False)
        self.app.format_var.set("WAV")
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            self.app.output_var.set(folder)
            with patch("main.shutil.which", return_value="ffmpeg"), patch.object(self.app.executor, "submit") as submit:
                self.app._confirm_selection()
                args = submit.call_args.args
                self.assertEqual([t.index for t in args[2]], [1, 3])
                self.assertEqual(args[3], "wav")
                self.assertEqual(args[4], Path(folder))
                self.assertFalse(args[5])


if __name__ == "__main__":
    unittest.main()
