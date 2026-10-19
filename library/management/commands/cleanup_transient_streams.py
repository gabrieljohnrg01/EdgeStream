from django.core.management.base import BaseCommand
from django.utils import timezone

from library.models import TransientStreamSession


class Command(BaseCommand):
    help = "Expire transient stream sessions and remove their isolated temporary output."

    def handle(self, *args, **options):
        now = timezone.now()
        expired = TransientStreamSession.objects.filter(expires_at__lte=now).exclude(
            status=TransientStreamSession.STATUS_STOPPED
        )
        # Worker/process teardown is implemented by the stream supervisor. Until
        # then, this command only marks expired DB records; it never touches
        # MEDIA_ROOT, HLS_ROOT, or permanent library files.
        count = expired.update(
            status=TransientStreamSession.STATUS_STOPPED,
            stopped_at=now,
            magnet_uri="",
            selected_file="",
        )
        # Also scrub magnet metadata from already-stopped sessions whose TTL passed.
        scrubbed = TransientStreamSession.objects.filter(
            expires_at__lte=now, status=TransientStreamSession.STATUS_STOPPED
        ).exclude(magnet_uri="").update(magnet_uri="", selected_file="")
        self.stdout.write(self.style.SUCCESS(
            f"Expired {count} session(s); scrubbed {scrubbed} stopped session(s). "
            "No media files were deleted."
        ))
