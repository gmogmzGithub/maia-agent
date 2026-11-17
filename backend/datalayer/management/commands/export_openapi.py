import json

from django.core.management.base import BaseCommand

from api.routes import api


class Command(BaseCommand):
    help = "Exporta el contrato OpenAPI para generar los tipos del frontend"

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(api.get_openapi_schema(), ensure_ascii=False, indent=2))
