"""Filesystem isolation helpers for transient HLS output.

The transient root is deliberately separate from MEDIA_ROOT/HLS_ROOT. Only a small
allowlist of flat HLS filenames is eligible for delivery; arbitrary user paths are
never accepted.
"""
import re
from pathlib import Path
from uuid import UUID

from django.conf import settings

_ALLOWED_ASSET = re.compile(r"^(?:index\.m3u8|segment_[0-9]{5}\.ts)$")


def transient_root() -> Path:
    configured = getattr(settings, "TRANSIENT_STREAM_ROOT", settings.BASE_DIR / "transient_streams")
    return Path(configured).resolve()


def session_output_dir(session_id) -> Path:
    """Return the isolated output directory for a valid session UUID."""
    session_uuid = UUID(str(session_id))
    root = transient_root()
    candidate = root / str(session_uuid)
    # Resolve symlinks and require the final path to remain under the configured root.
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise ValueError("Invalid transient session directory.")
    return resolved


def resolve_hls_asset(session_id, asset_name: str) -> Path | None:
    """Resolve an allowlisted regular file; reject traversal and symlink escapes."""
    if not isinstance(asset_name, str) or not _ALLOWED_ASSET.fullmatch(asset_name):
        return None
    try:
        directory = session_output_dir(session_id)
    except (TypeError, ValueError):
        return None
    candidate = directory / asset_name
    try:
        resolved = candidate.resolve(strict=True)
        if resolved.parent != directory or not resolved.is_file():
            return None
        return resolved
    except (OSError, RuntimeError):
        return None
