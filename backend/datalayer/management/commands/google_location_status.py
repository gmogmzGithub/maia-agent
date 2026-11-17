import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from datalayer.google_locations import configured
from datalayer.models import GoogleLocation, GoogleLocationUsage


class Command(BaseCommand):
    help = "Muestra disponibilidad y límites de ubicación sin claves ni consultas a Google."

    def handle(self, *args, **options):
        month = timezone.now().strftime("%Y-%m")
        self.stdout.write(
            json.dumps(
                {
                    "configured": configured(),
                    "browser_key_present": bool(settings.GOOGLE_MAPS_BROWSER_KEY),
                    "server_key_present": bool(settings.GOOGLE_MAPS_SERVER_KEY),
                    "month": month,
                    "limits": settings.GOOGLE_LOCATION_MONTHLY_LIMITS,
                    "requests_reserved": dict(
                        GoogleLocationUsage.objects.filter(month=month).values_list("sku", "count")
                    ),
                    "expired_points_awaiting_purge": GoogleLocation.objects.filter(
                        expires_at__lte=timezone.now(), latitude__isnull=False
                    ).count(),
                },
                indent=2,
            )
        )
