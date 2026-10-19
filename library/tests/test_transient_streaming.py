from django.test import SimpleTestCase

from library.transient_streaming import (
    SourceCandidate,
    rank_sources,
    score_source,
    select_video_file,
    validate_magnet_uri,
)

MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Example"


class MagnetValidationTests(SimpleTestCase):
    def test_accepts_info_hash_magnet(self):
        self.assertEqual(validate_magnet_uri(MAGNET), MAGNET)

    def test_rejects_non_magnet_and_missing_hash(self):
        for value in ("https://example.test/movie", "magnet:?dn=missing-hash", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_magnet_uri(value)


class SourceRankingTests(SimpleTestCase):
    def test_rejects_cam_remux_and_unreasonable_size(self):
        for title in ("Movie CAM 1080p", "Movie BluRay REMUX", "Movie WEB-DL sample"):
            with self.subTest(title=title):
                self.assertIsNone(score_source(SourceCandidate(title, MAGNET, 2_000_000_000)))
        self.assertIsNone(score_source(SourceCandidate("Movie 1080p WEB-DL", MAGNET, 10_000)))

    def test_prefers_reasonable_web_dl_release_over_lower_quality(self):
        candidates = [
            SourceCandidate("Film 720p HDTV x264", MAGNET, 1_500_000_000, 20),
            SourceCandidate("Film 1080p WEB-DL x264", MAGNET, 4_000_000_000, 8),
        ]
        self.assertIn("1080p", rank_sources(candidates)[0].title)


class VideoFileSelectionTests(SimpleTestCase):
    def test_selects_requested_episode_from_pack(self):
        files = [
            {"path": "Show/Show.S01E01.1080p.mkv", "size": 900_000_000},
            {"path": "Show/Show.S01E02.1080p.mkv", "size": 950_000_000},
            {"path": "Show/Sample/sample.mkv", "size": 80_000_000},
            {"path": "Show/subtitles.srt", "size": 20_000},
        ]
        selected = select_video_file(files, season=1, episode=2)
        self.assertEqual(selected["path"], "Show/Show.S01E02.1080p.mkv")

    def test_does_not_guess_episode_from_unmatched_pack(self):
        self.assertIsNone(select_video_file([
            {"path": "Show/Show.S01E01.mkv", "size": 900_000_000},
        ], season=1, episode=3))

    def test_selects_largest_valid_movie_file(self):
        files = [
            {"path": "Film/sample.mkv", "size": 80_000_000},
            {"path": "Film/Film.mp4", "size": 2_000_000_000},
            {"path": "Film/Film.srt", "size": 1_000},
        ]
        self.assertEqual(select_video_file(files)["path"], "Film/Film.mp4")
