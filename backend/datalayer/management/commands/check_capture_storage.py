"""Read-only audit of image references and persistent files."""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from datalayer.models import CaptureAsset


class Command(BaseCommand):
    help = "Comprueba archivos de captación sin modificarlos ni mostrar datos del propietario."

    def add_arguments(self, parser):
        parser.add_argument("--verify-images", action="store_true")
        parser.add_argument("--find-orphans", action="store_true")

    def handle(self, *args, **options):
        checked, errors = 0, 0
        referenced = set()
        for asset in CaptureAsset.objects.iterator():
            checked += 1
            referenced.add(asset.file.name)
            issue = "archivo no legible"
            try:
                if not asset.file.storage.exists(asset.file.name):
                    issue = "archivo ausente"
                    raise ValueError("archivo ausente")
                if asset.file.storage.size(asset.file.name) != asset.size:
                    issue = "tamaño distinto al registrado"
                    raise ValueError("tamaño distinto al registrado")
                if options["verify_images"] and asset.content_type.startswith("image/"):
                    with asset.file.open("rb") as source, Image.open(source) as image:
                        image.verify()
            except Exception:
                errors += 1
                # Exception text from storage can contain credentials or private paths.
                self.stderr.write(f"Archivo {asset.pk}: {issue}")
        orphan_count = 0
        if options["find_orphans"]:

            def scan(path):
                nonlocal orphan_count
                try:
                    directories, files = default_storage.listdir(path)
                except FileNotFoundError:
                    return
                for name in files:
                    if f"{path}/{name}" not in referenced:
                        orphan_count += 1
                for name in directories:
                    scan(f"{path}/{name}")

            scan("capture")
        self.stdout.write(
            f"Archivos comprobados: {checked}. Errores: {errors}. Posibles huérfanos: {orphan_count}."
        )
        if orphan_count:
            self.stdout.write(
                "No se borraron archivos. Revisar y respaldar antes de cualquier limpieza."
            )
        if errors:
            raise CommandError("El almacenamiento necesita revisión.")
