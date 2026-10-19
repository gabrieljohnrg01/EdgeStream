"""Pure helpers for ranking authorized torrent sources and selecting media files.

This module deliberately does not scrape indexers, start downloads, or touch the
permanent media library. A provider adapter may supply candidate metadata later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping
from urllib.parse import parse_qs, urlsplit

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts"}
JUNK_WORDS = re.compile(
    r"\b(cam|hdcam|camrip|telesync|tsrip|telecine|workprint|screener|"
    r"bdremux|remux|sample|trailer|extras?)\b",
    re.IGNORECASE,
)
PREFERRED_WORDS = re.compile(r"\b(web[- .]?dl|webrip|hdtv|bluray|blu[- .]?ray|x264|h264)\b", re.I)
EPISODE_RE = re.compile(r"(?i)(?:s(?P<season>\d{1,2})[ ._-]*e(?P<episode>\d{1,3})|"
                        r"(?P<season2>\d{1,2})x(?P<episode2>\d{1,3}))")


@dataclass(frozen=True)
class SourceCandidate:
    """Metadata returned by a trusted/authorized source adapter."""
    title: str
    magnet_uri: str
    size_bytes: int
    seeders: int = 0


def validate_magnet_uri(value: str) -> str:
    """Validate the shape of a magnet URI without resolving or fetching it."""
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Invalid magnet URI.")
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "magnet":
        raise ValueError("Only magnet: URIs are accepted.")
    params = parse_qs(parsed.query)
    if not any(item.startswith("urn:btih:") for item in params.get("xt", [])):
        raise ValueError("Magnet URI must include a BitTorrent info hash (xt=urn:btih:...).")
    return value


def score_source(candidate: SourceCandidate, *, min_bytes: int = 250_000_000,
                 max_bytes: int = 20_000_000_000) -> float | None:
    """Return a relative quality score, or None for a source we should reject."""
    title = (candidate.title or "").strip()
    if not title or candidate.size_bytes < min_bytes or candidate.size_bytes > max_bytes:
        return None
    if JUNK_WORDS.search(title):
        return None
    try:
        validate_magnet_uri(candidate.magnet_uri)
    except ValueError:
        return None

    score = 10.0
    if re.search(r"\b(2160p|4k|uhd)\b", title, re.I):
        score += 1.0
    elif re.search(r"\b1080p\b", title, re.I):
        score += 3.0
    elif re.search(r"\b720p\b", title, re.I):
        score += 2.0
    elif re.search(r"\b480p\b", title, re.I):
        score += 0.5
    if PREFERRED_WORDS.search(title):
        score += 3.0
    if re.search(r"\bx265\b|\bhevc\b", title, re.I):
        score -= 1.0
    if re.search(r"\b(proper|repack)\b", title, re.I):
        score += 0.25
    score += min(max(int(candidate.seeders or 0), 0), 100) / 50.0
    size_gb = candidate.size_bytes / 1_000_000_000
    score -= max(0.0, size_gb - 8.0) * 0.15
    return round(score, 3)


def rank_sources(candidates: Iterable[SourceCandidate], **score_options) -> list[SourceCandidate]:
    """Filter and rank candidate sources, best first, without network access."""
    ranked = []
    for candidate in candidates:
        score = score_source(candidate, **score_options)
        if score is not None:
            ranked.append((score, candidate))
    ranked.sort(key=lambda item: (item[0], item[1].seeders, item[1].title.lower()), reverse=True)
    return [candidate for _, candidate in ranked]


def select_video_file(files: Iterable[Mapping], *, season: int | None = None,
                      episode: int | None = None) -> Mapping | None:
    """Choose a main video file from torrent file metadata."""
    choices = []
    for item in files:
        name = str(item.get("path") or item.get("name") or "")
        path = PurePosixPath(name)
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if any(part.lower() in {"sample", "extras", "featurettes", "proof"} for part in path.parts):
            continue
        if re.search(r"(?i)\b(sample|trailer|extras?)\b", path.stem):
            continue
        size = int(item.get("size") or item.get("size_bytes") or 0)
        if size < 50_000_000:
            continue

        episode_match = EPISODE_RE.search(path.stem)
        episode_score = 0
        if season is not None and episode is not None:
            if not episode_match:
                continue
            actual_season = int(episode_match.group("season") or episode_match.group("season2"))
            actual_episode = int(episode_match.group("episode") or episode_match.group("episode2"))
            if (actual_season, actual_episode) != (season, episode):
                continue
            episode_score = 1
        score = episode_score * 1_000_000 + min(size, 30_000_000_000)
        choices.append((score, item))
    if not choices:
        return None
    choices.sort(key=lambda pair: pair[0], reverse=True)
    return choices[0][1]
