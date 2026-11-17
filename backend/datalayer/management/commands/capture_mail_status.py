"""Read-only configuration summary. Never prints credentials or recipient addresses."""

import json

from django.core.management.base import BaseCommand
from django.db.models import Count

from datalayer.capture_mail import configuration
from datalayer.models import CaptureDelivery


class Command(BaseCommand):
    help = "Muestra configuración y estados de correo de captación sin enviar mensajes."

    def handle(self, *args, **options):
        result = configuration()
        result["delivery_counts"] = {
            row["status"]: row["total"]
            for row in CaptureDelivery.objects.filter(channel="email")
            .values("status")
            .annotate(total=Count("pk"))
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
