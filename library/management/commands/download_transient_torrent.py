"""Download the selected video from a supplied magnet, then hand it to FFmpeg.

This uses the libtorrent Python binding installed by the host OS. It deliberately
waits for the selected file to finish downloading before FFmpeg opens it, avoiding
corrupt reads from missing torrent pieces. It is not instant piece-aware streaming.
"""
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.models import TransientStreamSession
from library.transient_streaming import select_video_file, validate_magnet_uri
from library.transient_streaming_runtime import session_output_dir


class Command(BaseCommand):
    help = "Download a session magnet's selected video, then render it as HLS."

    def add_arguments(self, parser):
        parser.add_argument("session_id", help="Transient session UUID")
        parser.add_argument("--season", type=int, default=None, help="Season number for a season pack")
        parser.add_argument("--episode", type=int, default=None, help="Episode number for a season pack")

    def handle(self, *args, **options):
        try:
            session = TransientStreamSession.objects.get(pk=options["session_id"])
        except (TransientStreamSession.DoesNotExist, ValueError):
            raise CommandError("Transient session not found.")

        if session.status not in (TransientStreamSession.STATUS_PENDING, TransientStreamSession.STATUS_STARTING):
            raise CommandError(f"Session cannot start from status {session.status}.")
        if session.expires_at <= timezone.now():
            self._stop_session(session, "Session expired before the torrent worker started.")
            raise CommandError("Transient session has expired.")
        try:
            magnet_uri = validate_magnet_uri(session.magnet_uri)
        except ValueError:
            self._fail_session(session, "Session has no valid magnet URI.")
            raise CommandError("Session has no valid magnet URI.")

        try:
            import libtorrent as lt
        except ImportError:
            self._fail_session(session, "Python libtorrent binding is not installed.")
            raise CommandError(
                "Python libtorrent is not installed. Install the OS package that matches your Python, "
                "then retry; see docs/TRANSIENT_STREAMING.md."
            )

        directory = session_output_dir(session.pk)
        download_dir = directory / "download"
        download_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        torrent_session = lt.session()
        params = lt.parse_magnet_uri(magnet_uri)
        params.save_path = str(download_dir)
        handle = torrent_session.add_torrent(params)

        session.status = TransientStreamSession.STATUS_STARTING
        session.last_error = ""
        session.save(update_fields=["status", "last_error"])
        try:
            while not handle.has_metadata():
                session.refresh_from_db()
                if self._should_stop(session):
                    self._stop_session(session, "Session stopped or expired while fetching torrent metadata.")
                    return
                time.sleep(1)

            info = handle.torrent_file()
            file_storage = info.files()
            file_items = [
                {"path": file_storage.file_path(i), "size": file_storage.file_size(i), "index": i}
                for i in range(file_storage.num_files())
            ]
            selected = select_video_file(
                file_items, season=options["season"], episode=options["episode"]
            )
            if selected is None:
                self._fail_session(session, "No suitable video file matched this torrent.")
                raise CommandError("No suitable video file matched this torrent.")

            selected_index = int(selected["index"])
            relative_source = Path(str(selected["path"]))
            if relative_source.is_absolute() or ".." in relative_source.parts:
                self._fail_session(session, "Torrent file path failed validation.")
                raise CommandError("Torrent file path failed validation.")

            priorities = [0] * file_storage.num_files()
            priorities[selected_index] = 7
            handle.prioritize_files(priorities)
            handle.set_sequential_download(True)
            selected_size = int(selected["size"])
            selected_path = (download_dir / relative_source).resolve()
            try:
                selected_path.relative_to(download_dir.resolve())
            except ValueError:
                self._fail_session(session, "Selected torrent file escaped the session download directory.")
                raise CommandError("Selected torrent file path is unsafe.")

            session.selected_file = str(selected_path.relative_to(directory.resolve()))
            session.save(update_fields=["selected_file"])
            self.stdout.write("Downloading selected video file; other torrent files are deprioritized.")

            while True:
                session.refresh_from_db()
                if self._should_stop(session):
                    self._stop_session(session, "Session stopped or expired during torrent download.")
                    return
                try:
                    file_progress = handle.file_progress()
                    downloaded = int(file_progress[selected_index])
                except (IndexError, TypeError):
                    downloaded = 0
                if downloaded >= selected_size and selected_path.is_file():
                    break
                time.sleep(1)

            # Never expose the file until the selected file is complete.
            session.refresh_from_db()
            if self._should_stop(session):
                self._stop_session(session, "Session stopped before HLS rendering.")
                return
            self.stdout.write("Selected file is complete; starting FFmpeg HLS rendering.")
            call_command(
                "run_transient_hls",
                str(session.pk),
                source=str(selected_path.relative_to(directory.resolve())),
            )
        except CommandError:
            session.refresh_from_db()
            if session.status not in (TransientStreamSession.STATUS_STOPPED, TransientStreamSession.STATUS_FAILED):
                self._fail_session(session, "Transient torrent/HLS worker failed.")
            raise
        except Exception as exc:
            session.refresh_from_db()
            if session.status not in (TransientStreamSession.STATUS_STOPPED, TransientStreamSession.STATUS_FAILED):
                self._fail_session(session, f"Torrent worker error: {type(exc).__name__}")
            raise CommandError(f"Transient torrent worker failed ({type(exc).__name__}).") from exc

    @staticmethod
    def _should_stop(session):
        return session.status == TransientStreamSession.STATUS_STOPPED or session.expires_at <= timezone.now()

    @staticmethod
    def _stop_session(session, reason):
        session.status = TransientStreamSession.STATUS_STOPPED
        session.stopped_at = timezone.now()
        session.last_error = reason[:500]
        session.magnet_uri = ""
        session.save(update_fields=["status", "stopped_at", "last_error", "magnet_uri"])

    @staticmethod
    def _fail_session(session, reason):
        session.status = TransientStreamSession.STATUS_FAILED
        session.last_error = reason[:500]
        session.magnet_uri = ""
        session.save(update_fields=["status", "last_error", "magnet_uri"])
