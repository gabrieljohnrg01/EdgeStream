"""Render a completed, session-local video file into rolling HLS output.

This command is the FFmpeg half of the worker pipeline. A torrent bridge is not yet
implemented; it must place a fully downloaded file inside this session directory
before invoking this command. It intentionally never reads from MEDIA_ROOT.
"""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.models import TransientStreamSession
from library.transient_streaming_runtime import session_output_dir


class Command(BaseCommand):
    help = "Render a completed video inside a transient session directory to HLS."

    def add_arguments(self, parser):
        parser.add_argument("session_id", help="Transient session UUID")
        parser.add_argument("--source", required=True, help="Video path relative to the session directory")
        parser.add_argument("--startup-timeout", type=int, default=90)

    def handle(self, *args, **options):
        session_id = options["session_id"]
        try:
            session = TransientStreamSession.objects.get(pk=session_id)
        except (TransientStreamSession.DoesNotExist, ValueError):
            raise CommandError("Transient session not found.")

        if session.status not in (TransientStreamSession.STATUS_PENDING, TransientStreamSession.STATUS_STARTING):
            raise CommandError(f"Session cannot start from status {session.status}.")
        if session.expires_at <= timezone.now():
            raise CommandError("Transient session has expired.")

        directory = session_output_dir(session.pk)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        source_arg = Path(options["source"])
        if source_arg.is_absolute() or ".." in source_arg.parts:
            raise CommandError("--source must be a relative path inside the session directory.")
        source = (directory / source_arg).resolve()
        try:
            source.relative_to(directory.resolve())
        except ValueError:
            raise CommandError("Source file must remain inside the session directory.")
        if not source.is_file() or source.stat().st_size < 1:
            raise CommandError("Source file does not exist or is empty.")

        ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
        if not ffmpeg:
            raise CommandError("FFmpeg was not found. Install FFmpeg or set FFMPEG_BINARY.")

        playlist = directory / "index.m3u8"
        segment_pattern = directory / "segment_%05d.ts"
        # Avoid stale output from a previous failed attempt being mistaken for this run.
        for old in directory.glob("segment_[0-9][0-9][0-9][0-9][0-9].ts"):
            old.unlink(missing_ok=True)
        playlist.unlink(missing_ok=True)

        session.status = TransientStreamSession.STATUS_STARTING
        session.last_error = ""
        session.selected_file = str(source.relative_to(directory))
        session.save(update_fields=["status", "last_error", "selected_file"])

        command = [
            ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y",
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
            "-hls_playlist_type", "event",
            "-hls_segment_filename", str(segment_pattern),
            str(playlist),
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        activated = False
        deadline = time.monotonic() + max(5, min(options["startup_timeout"], 300))
        try:
            while process.poll() is None:
                session.refresh_from_db()
                if session.status == TransientStreamSession.STATUS_STOPPED or session.expires_at <= timezone.now():
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    if session.status != TransientStreamSession.STATUS_STOPPED:
                        session.status = TransientStreamSession.STATUS_STOPPED
                        session.stopped_at = timezone.now()
                        session.magnet_uri = ""
                        session.save(update_fields=["status", "stopped_at", "magnet_uri"])
                    return

                ready = playlist.is_file() and any(directory.glob("segment_[0-9][0-9][0-9][0-9][0-9].ts"))
                if ready and not activated:
                    session.status = TransientStreamSession.STATUS_ACTIVE
                    session.save(update_fields=["status"])
                    activated = True
                    self.stdout.write(self.style.SUCCESS("HLS playlist and first segment are ready."))

                if not activated and time.monotonic() > deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    session.refresh_from_db()
                    if session.status != TransientStreamSession.STATUS_STOPPED:
                        session.status = TransientStreamSession.STATUS_FAILED
                        session.last_error = "FFmpeg startup timed out."
                        session.magnet_uri = ""
                        session.save(update_fields=["status", "last_error", "magnet_uri"])
                    raise CommandError("FFmpeg did not produce a playlist and segment before the startup timeout.")
                time.sleep(0.5)

            if process.returncode != 0:
                session.refresh_from_db()
                if session.status != TransientStreamSession.STATUS_STOPPED:
                    session.status = TransientStreamSession.STATUS_FAILED
                    session.last_error = f"FFmpeg exited with code {process.returncode}"[-500:]
                    session.magnet_uri = ""
                    session.save(update_fields=["status", "last_error", "magnet_uri"])
                raise CommandError(f"FFmpeg failed (exit {process.returncode}). Check server logs for details.")

            if not activated:
                session.refresh_from_db()
                if session.status != TransientStreamSession.STATUS_STOPPED:
                    session.status = TransientStreamSession.STATUS_FAILED
                    session.last_error = "FFmpeg finished without producing playable HLS output."
                    session.magnet_uri = ""
                    session.save(update_fields=["status", "last_error", "magnet_uri"])
                raise CommandError("FFmpeg finished without producing playable HLS output.")
            self.stdout.write(self.style.SUCCESS("HLS render completed. Session remains available until expiry or stop."))
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
