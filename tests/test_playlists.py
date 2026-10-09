import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sources
from downloads import DownloadEngine as AudioExtractorApp


class SourceTests(unittest.TestCase):
    def test_platform_boundary(self):
        for url in ["https://youtube.com/watch?v=x", "https://music.youtube.com/x", "https://youtu.be/x"]:
            self.assertEqual(sources.platform(url), "youtube")
        self.assertEqual(sources.platform("https://soundcloud.com/a/sets/b"), "soundcloud")
        self.assertEqual(sources.platform("https://open.spotify.com/playlist/abc"), "spotify")
        for url in ["https://evilyoutube.com/x", "https://youtube.com.evil.com/x", "file://youtube.com/x", "https://user:pass@youtube.com/x"]:
            self.assertIsNone(sources.platform(url))

    @patch("sources.yt_dlp.YoutubeDL")
    def test_playlist_keeps_order_duplicates_and_skips_missing(self, cls):
        cls.return_value.__enter__.return_value.extract_info.return_value = {
            "title": "Demo", "entries": [
                {"id": "abcdefghijk", "title": "Song"}, None,
                {"id": "abcdefghijk", "title": "Song"},
                {"id": "12345678901", "availability": "private"}]}
        result = sources.resolve("https://youtube.com/playlist?list=demo")
        self.assertTrue(result.playlist)
        self.assertEqual([t.index for t in result.tracks], [1, 3])
        self.assertEqual(result.skipped, 2)
        self.assertFalse(cls.call_args.args[0]["noplaylist"])
        cls.return_value.__enter__.return_value.extract_info.assert_called_once_with(
            "https://youtube.com/playlist?list=demo", download=False)

    @patch("sources.yt_dlp.YoutubeDL")
    def test_soundcloud_single(self, cls):
        cls.return_value.__enter__.return_value.extract_info.return_value = {
            "title": "Song", "webpage_url": "https://soundcloud.com/artist/song"}
        result = sources.resolve("https://soundcloud.com/artist/song")
        self.assertFalse(result.playlist)
        self.assertEqual(len(result.tracks), 1)

    @patch("sources.yt_dlp.YoutubeDL")
    def test_empty_source_is_error(self, cls):
        cls.return_value.__enter__.return_value.extract_info.return_value = {"entries": []}
        with self.assertRaises(ValueError):
            sources.resolve("https://youtube.com/playlist?list=demo")

    def test_spotify_pagination_and_new_item_field(self):
        client = MagicMock()
        client.playlist.return_value = {"name": "List"}
        client.playlist_items.return_value = {"items": [{"item": {"name": "A"}}], "next": "next"}
        client.next.return_value = {"items": [{"track": {"name": "B"}}, {"item": None}], "next": None}
        name, tracks = sources.spotify_tracks(client, "playlist", "abc")
        self.assertEqual(name, "List")
        self.assertEqual([t["name"] if t else None for t in tracks], ["A", "B", None])
        client.playlist_items.assert_called_once_with("abc")

    @patch("sources.yt_dlp.YoutubeDL")
    @patch("sources.spotify_client")
    @patch("sources.spotify_tracks")
    def test_spotify_matches_before_download(self, tracks, client, cls):
        tracks.return_value = ("Demo", [
            {"name": "Original", "artists": [{"name": "Artist"}], "type": "track"},
            {"name": "Local", "is_local": True}])
        cls.return_value.__enter__.return_value.extract_info.return_value = {
            "entries": [{"id": "abcdefghijk", "title": "YouTube version"}]}
        result = sources.resolve("https://open.spotify.com/playlist/abc", client_id="id")
        self.assertTrue(result.spotify)
        self.assertEqual(result.tracks[0].original, "Artist — Original")
        self.assertEqual(result.tracks[0].title, "YouTube version")
        self.assertEqual(result.skipped, 1)
        self.assertIn("download", cls.return_value.__enter__.return_value.extract_info.call_args.kwargs)
        self.assertFalse(cls.return_value.__enter__.return_value.extract_info.call_args.kwargs["download"])

    def test_public_spotify_never_requests_login_or_isrc_service(self):
        module = SimpleNamespace(Spotify=MagicMock())
        with patch.dict(sys.modules, {"SpotipyFree": module}):
            sources.spotify_client()
        module.Spotify.assert_called_once_with(login=False, getIsrc=False)

    @patch("sources.spotify_client")
    def test_spotify_access_denied_is_actionable(self, client):
        client.side_effect = RuntimeError("Forbidden")
        with self.assertRaisesRegex(ValueError, "playlist pública"):
            sources.resolve("https://open.spotify.com/playlist/abc", client_id="id")


class BatchTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(events=queue.Queue(), last_progress_emit=0)
        for name in ["_unique_folder", "_unique_file", "_safe_name"]:
            setattr(app, name, getattr(AudioExtractorApp, name))
        app._emit_log = MagicMock()
        app._emit_progress = MagicMock()
        app._download_progress = MagicMock()
        app._download_track = MagicMock()
        return app

    def test_partial_failure_continues_and_preserves_previous_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "Demo").mkdir()
            (target / "Demo" / "old.mp3").write_text("keep")
            tracks = [sources.Track("A", "https://youtu.be/a", 1), sources.Track("B", "https://youtu.be/b", 2), sources.Track("C", "https://youtu.be/c", 3)]
            app = self.app()
            app._download_track.side_effect = [target / "A.mp3", RuntimeError("failed"), target / "C.mp3"]
            AudioExtractorApp._batch_worker(app, sources.Collection("Demo", tracks, True), tracks, "mp3", target, False)
            self.assertEqual(app._download_track.call_count, 3)
            self.assertEqual((target / "Demo" / "old.mp3").read_text(), "keep")
            report = json.loads((target / "Demo (2)" / "fr3do-resultados.json").read_text())
            self.assertEqual([r["status"] for r in report], ["ok", "error", "ok"])
            self.assertEqual(app.events.get()[0], "partial")

    def test_all_failures_do_not_signal_success(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app()
            app._download_track.side_effect = RuntimeError("failed")
            tracks = [sources.Track("A", "https://youtu.be/a", 1)]
            AudioExtractorApp._batch_worker(app, sources.Collection("Demo", tracks, False), tracks, "mp3", Path(folder), False)
            self.assertEqual(app.events.get()[0], "failure")

    @patch("downloads.yt_dlp.YoutubeDL")
    def test_single_track_moves_converted_file_and_cleans_temp(self, cls):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app()
            app.batch_position, app.batch_total = 0, 2
            def extract(url, download):
                template = cls.call_args.args[0]["outtmpl"]
                Path(template).parent.joinpath("001 - Song [id].mp3").write_bytes(b"audio")
                return {"title": "Song"}
            cls.return_value.__enter__.return_value.extract_info.side_effect = extract
            result = AudioExtractorApp._download_track(app, sources.Track("Song", "https://youtu.be/a", 1), "mp3", Path(folder), False)
            self.assertEqual(result.read_bytes(), b"audio")
            self.assertFalse(list(Path(folder).glob("fr3do_*")))
            self.assertTrue(cls.call_args.args[0]["noplaylist"])

    def test_unique_filename_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "Song.mp3").touch()
            self.assertEqual(AudioExtractorApp._unique_file(target, "Song.mp3").name, "Song (2).mp3")


if __name__ == "__main__":
    unittest.main()
