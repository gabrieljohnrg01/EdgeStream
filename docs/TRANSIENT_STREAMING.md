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

## Session API (metadata only)

The authenticated endpoints are now registered:

- GET /api/transient-streams/ — list the signed-in user's latest sessions.
- POST /api/transient-streams/ with JSON containing a magnet_uri — validate and create a pending session.
- GET /api/transient-streams/<uuid>/ — read a session owned by the signed-in user.
- POST /api/transient-streams/<uuid>/ — stop the session and scrub its magnet metadata.

Creation is limited to two unexpired pending/starting/active sessions per user and gives each session a three-hour TTL. Responses do not expose magnet URIs. Other users' session IDs return 404. **These endpoints only manage session metadata: creation does not download a torrent or return a playable URL until the worker is implemented.**

## Opt-in worker autostart

Session creation can launch the torrent/HLS worker as a separate backend process when
`TRANSIENT_STREAM_WORKERS_ENABLED=true`. It is disabled by default so deployments
that have not installed the native torrent binding do not launch failing workers.
The child process log is written to `worker.log` inside the session's private output
directory; it is not exposed by the HLS asset endpoint.

On Debian/Ubuntu hosts, install the native dependencies:

```bash
sudo apt update
sudo apt install ffmpeg python3-libtorrent
```

If Django runs in a virtual environment, ensure that environment can import the
OS-provided `libtorrent` binding (for example, create the venv with
`--system-site-packages`, or use a compatible package for the exact Python version).
Then set `TRANSIENT_STREAM_WORKERS_ENABLED=true` in the backend environment and
restart the Django service. Ensure the configured `TRANSIENT_STREAM_ROOT` is writable
only by the backend service account and has enough disk space. Do not enable autostart
until the native binding and FFmpeg are installed.

The worker currently downloads the chosen video file to completion before launching
FFmpeg. It does not yet implement immediate playback during torrent download or
piece-deadline-based random seeking. A three-hour session TTL and two-session per-user
limit remain in effect.

## FFmpeg rendering stage

`python manage.py run_transient_hls <session-uuid> --source <relative-video-path>` renders a **completed** video already placed inside that session's isolated directory into an event-style HLS playlist and four-second MPEG-TS segments. It copies the video stream and transcodes audio to AAC, then marks the session ACTIVE once the playlist and first segment exist. The command monitors the session record and terminates FFmpeg when the session is stopped or expires. FFmpeg must be installed on the host; `FFMPEG_BINARY` can override its executable path.

This is only the FFmpeg stage. There is not yet a torrent downloader that places a completed source into the session directory or automatically launches this command. It does not provide instant torrent-to-HLS playback while the torrent is downloading.

## HLS asset delivery

The authenticated session detail endpoint now returns a short-lived `playback_url`
when a session is ACTIVE. The URL is signed for ten minutes so native HLS clients
that cannot attach the application's Bearer token to each segment request can play
the playlist. The playlist handler rewrites only allowlisted `segment_00000.ts`
style references and propagates the signed token. Assets are owner-scoped, checked
against session status and expiry, restricted to a fixed filename allowlist, and
sent with `Cache-Control: no-store` headers.

This is delivery plumbing only. A worker must create a valid `index.m3u8` and
matching segment files inside the session's directory before the API will serve them.
The current code does not yet launch libtorrent or FFmpeg, and it does not claim a
session is playable before the worker sets it ACTIVE. The output root is configured
by `TRANSIENT_STREAM_ROOT` and defaults to `BASE_DIR/transient_streams`, outside
the permanent media/HLS directories.

## Session persistence and expiry

`TransientStreamSession` now provides a separate owner-scoped database record with a UUID, lifecycle status, expiry timestamp, and private magnet metadata. The `cleanup_transient_streams` management command marks expired sessions stopped and scrubs their magnet/file metadata. It intentionally does not delete any media files. A future worker supervisor must terminate its child process and remove only the validated session directory before physical cleanup can safely be enabled.

Example maintenance command:

```bash
python manage.py cleanup_transient_streams
```

Schedule this command periodically after deployment. It is metadata cleanup only at this stage; the torrent/FFmpeg worker and session HTTP endpoints are not implemented yet.

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
