import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.models import CatalogTitle


SECTIONS = {
    "trending_movies": ("MOVIE", "trending/movie/day"),
    "popular_movies": ("MOVIE", "movie/popular"),
    "top_rated_movies": ("MOVIE", "movie/top_rated"),
    "upcoming_movies": ("MOVIE", "movie/upcoming"),
    "trending_tv": ("TV", "trending/tv/day"),
    "popular_tv": ("TV", "tv/popular"),
    "top_rated_tv": ("TV", "tv/top_rated"),
}


class Command(BaseCommand):
    help = "Sync selected TMDB movie and TV catalog sections into the local database."

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=1, help="Pages to import per section (20 results per page).")
        parser.add_argument(
            "--sections",
            default=",".join(SECTIONS),
            help="Comma-separated section names. Choices: " + ", ".join(SECTIONS),
        )
        parser.add_argument("--language", default="en-US", help="TMDB metadata language, e.g. en-US.")
        parser.add_argument("--region", default="", help="Optional ISO 3166-1 region, e.g. PH (used for upcoming movies).")

    def handle(self, *args, **options):
        api_key = os.environ.get("TMDB_API_KEY", "").strip()
        read_token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
        if not api_key and not read_token:
            raise CommandError(
                "Set TMDB_API_KEY (v3 API key) or TMDB_READ_ACCESS_TOKEN (API Read Access Token) in your environment."
            )

        pages = options["pages"]
        if not 1 <= pages <= 500:
            raise CommandError("--pages must be between 1 and 500.")

        requested = [item.strip() for item in options["sections"].split(",") if item.strip()]
        invalid = sorted(set(requested) - set(SECTIONS))
        if invalid:
            raise CommandError("Unknown section(s): " + ", ".join(invalid))

        created_count = updated_count = 0
        for section in requested:
            media_type, endpoint = SECTIONS[section]
            for page in range(1, pages + 1):
                payload = self.fetch_page(
                    endpoint,
                    page=page,
                    language=options["language"],
                    api_key=api_key,
                    read_token=read_token,
                    region=options["region"] if section == "upcoming_movies" else "",
                )
                results = payload.get("results", [])
                if not results:
                    break

                for item in results:
                    tmdb_id = item.get("id")
                    title = item.get("title") if media_type == "MOVIE" else item.get("name")
                    if not tmdb_id or not title:
                        continue

                    release = item.get("release_date") if media_type == "MOVIE" else item.get("first_air_date")
                    try:
                        release_date = datetime.strptime(release, "%Y-%m-%d").date() if release else None
                    except (TypeError, ValueError):
                        release_date = None

                    defaults = {
                        "title": title[:255],
                        "original_title": (item.get("original_title") or item.get("original_name") or "")[:255],
                        "overview": item.get("overview") or "",
                        "poster_path": item.get("poster_path") or "",
                        "backdrop_path": item.get("backdrop_path") or "",
                        "release_date": release_date,
                        "original_language": item.get("original_language") or "",
                        "vote_average": item.get("vote_average") or 0,
                        "vote_count": item.get("vote_count") or 0,
                        "popularity": item.get("popularity") or 0,
                        "genre_ids": item.get("genre_ids") or [],
                        "last_synced": timezone.now(),
                    }
                    obj, created = CatalogTitle.objects.get_or_create(
                        media_type=media_type,
                        tmdb_id=tmdb_id,
                        defaults={**defaults, "sections": [section]},
                    )
                    if created:
                        created_count += 1
                    else:
                        current_sections = obj.sections if isinstance(obj.sections, list) else []
                        if section not in current_sections:
                            current_sections.append(section)
                        for key, value in defaults.items():
                            setattr(obj, key, value)
                        obj.sections = current_sections
                        obj.save()
                        updated_count += 1

                self.stdout.write(f"{section}: page {page}, received {len(results)} results")
                if page >= payload.get("total_pages", page):
                    break

        self.stdout.write(self.style.SUCCESS(
            f"TMDB catalog sync complete. Created: {created_count}; updated: {updated_count}; total catalog records: {CatalogTitle.objects.count()}."
        ))

    @staticmethod
    def fetch_page(endpoint, page, language, api_key, read_token, region=""):
        params = {"page": page, "language": language, "include_adult": "false"}
        if api_key:
            params["api_key"] = api_key
        if region:
            params["region"] = region
        url = "https://api.themoviedb.org/3/" + endpoint + "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json"}
        if read_token:
            headers["Authorization"] = "Bearer " + read_token
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise CommandError("TMDB rejected the credentials. Check your API key/token and its permissions.") from exc
            if exc.code == 429:
                raise CommandError("TMDB rate limit reached. Wait before retrying with fewer pages.") from exc
            raise CommandError(f"TMDB API returned HTTP {exc.code} for {endpoint}, page {page}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not retrieve {endpoint}, page {page}: {exc}") from exc
