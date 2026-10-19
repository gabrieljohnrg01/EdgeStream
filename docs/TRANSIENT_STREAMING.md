# Transient torrent-to-HLS streaming

This feature is being added alongside the existing permanent-media library. It must
not reuse the permanent conversion queue: that worker marks library items converted
and deletes its source file after a successful conversion.

## Boundaries

- Permanent movies/episodes continue to use the existing `/media/` and `/hls/` paths.
- Transient streams use a dedicated per-session temporary directory outside those
  permanent paths and must be removed when a session ends or expires.
- Do not scrape arbitrary torrent-indexing sites inside the request path. Source
  discovery should be implemented as explicit provider adapters, using only sources
  the operator is authorized to access and media the user is authorized to stream.
- Do not persist full magnet URIs in logs. A later session model should scope each
  session to its owner, expire it, and enforce per-user and global resource limits.
- The frontend may be deployed separately from the backend; API URLs, CORS, and
  temporary HLS URLs therefore need explicit configuration and access controls.

## Initial pure helpers

`library.transient_streaming` provides deterministic helpers for validating a magnet
URI's shape, ranking supplied source candidates, and selecting the main video file
(or an exact season/episode match). These helpers do not make network requests and
do not start a torrent download.

## Implementation sequence

1. Source validation/ranking and deterministic file selection (this commit).
2. Add a session model, migration, owner-scoped create/status/stop endpoints, TTL and
   cleanup command; keep the permanent conversion queue unchanged.
3. Add a supervised streaming worker using libtorrent and FFmpeg, with bounded
   concurrency, piece-aware buffering, and an isolated temporary HLS directory.
4. Serve session playlists and segments with no-store headers and session authorization.
5. Integrate player source selection, native HLS support detection, hls.js buffering
   configuration, debounced seeks, progress heartbeat, and teardown on navigation.
6. Add tests and deployment documentation for low-storage Linux/Termux hosts, HTTPS
   tunnel configuration, optional proxy support, and failure recovery.

## Important streaming design constraint

A partially downloaded torrent file cannot safely be handed to FFmpeg as if every
byte were already available: unread pieces may look like zero-filled data. The worker
must coordinate torrent piece availability with media reads and seeking, or use a
well-defined sequential streaming bridge. Merely piping the file path into FFmpeg is
not sufficient for correct random seeking.
