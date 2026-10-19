"""Process and temporary-directory supervisor for transient HLS sessions.

This module deliberately accepts a local input path supplied by a trusted torrent
bridge. It does not treat an incomplete libtorrent file as readable media. The
bridge must guarantee the selected byte stream is safe to read before calling
start_ffmpeg_hls; the torrent-piece-aware bridge is a separate integration step.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Sequence


class WorkerError(RuntimeError):
    """Raised when a transient worker cannot safely be started."""


class HLSProcessSupervisor:
    """Owns per-session FFmpeg processes and temporary output directories."""

    def __init__(self, root: str | Path, *, ffmpeg_binary: str = "ffmpeg",
                 segment_seconds: int = 4, list_size: int = 8):
        self.root = Path(root).resolve()
        self.ffmpeg_binary = ffmpeg_binary
        self.segment_seconds = max(2, min(int(segment_seconds), 10))
        self.list_size = max(3, min(int(list_size), 20))
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        # UUIDs are expected, but reject path separators and dot components anyway.
        if not session_id or any(ch not in "0123456789abcdefABCDEF-" for ch in session_id):
            raise WorkerError("Invalid session identifier.")
        directory = (self.root / session_id).resolve()
        if directory.parent != self.root:
            raise WorkerError("Session path escapes transient root.")
        return directory

    def start_ffmpeg_hls(self, session_id: str, input_path: str | Path,
                         *, extra_input_args: Sequence[str] = ()) -> Path:
        source = Path(input_path).resolve()
        if not source.is_file():
            raise WorkerError("Input source is not a readable file.")
        directory = self.session_dir(session_id)
        with self._lock:
            current = self._processes.get(session_id)
            if current is not None and current.poll() is None:
                raise WorkerError("A worker is already running for this session.")
            directory.mkdir(parents=True, exist_ok=True)
            playlist = directory / "index.m3u8"
            segment_pattern = directory / "segment_%05d.ts"
            command = [
                self.ffmpeg_binary, "-hide_banner", "-loglevel", "warning",
                "-nostdin", "-y", *extra_input_args, "-i", str(source),
                "-map", "0:v:0?", "-map", "0:a:0?", "-sn",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-f", "hls", "-hls_time", str(self.segment_seconds),
                "-hls_list_size", str(self.list_size),
                "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
                "-hls_segment_filename", str(segment_pattern), str(playlist),
            ]
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    start_new_session=(os.name == "posix"),
                )
            except OSError as exc:
                raise WorkerError(f"Unable to start FFmpeg: {exc}") from exc
            self._processes[session_id] = process
        return playlist

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            process = self._processes.get(session_id)
            return process is not None and process.poll() is None

    def stop(self, session_id: str, *, remove_output: bool = True) -> None:
        directory = self.session_dir(session_id)
        with self._lock:
            process = self._processes.pop(session_id, None)
        if process is not None and process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if remove_output and directory.exists():
            # Resolve and verify the directory again before destructive cleanup.
            if directory.parent != self.root or directory == self.root:
                raise WorkerError("Refusing to remove a path outside transient root.")
            shutil.rmtree(directory, ignore_errors=False)

    def stop_all(self) -> None:
        with self._lock:
            session_ids = list(self._processes)
        for session_id in session_ids:
            self.stop(session_id, remove_output=True)
