from django.core.management.base import BaseCommand

from datalayer.models import Property


class Command(BaseCommand):
    help = "Carga cuatro propiedades ficticias identificadas como PRUEBA; no crea usuarios"

    def handle(self, *args, **options):
        examples = [
            (
                "PRUEBA-001",
                "PRUEBA · Casa con jardín en La Estancia",
                "rent",
                "house",
                "La Estancia",
                "32000",
                3,
                2,
                2,
                True,
                True,
                True,
            ),
            (
                "PRUEBA-002",
                "PRUEBA · Casa luminosa en Ciudad Granja",
                "rent",
                "house",
                "Ciudad Granja",
                "37000",
                3,
                3,
                2,
                False,
                None,
                True,
            ),
            (
                "PRUEBA-003",
                "PRUEBA · Departamento en Jardines Universidad",
                "rent",
                "apartment",
                "Jardines Universidad",
                "24000",
                2,
                2,
                1,
                True,
                True,
                None,
            ),
            (
                "PRUEBA-004",
                "PRUEBA · Casa en venta en La Estancia",
                "sale",
                "house",
                "La Estancia",
                "6500000",
                4,
                3,
                2,
                False,
                True,
                True,
            ),
        ]
        for (
            reference,
            title,
            operation,
            kind,
            neighborhood,
            price,
            bedrooms,
            bathrooms,
            parking,
            furnished,
            pets,
            schools,
        ) in examples:
            _, created = Property.objects.get_or_create(
                reference=reference,
                defaults={
                    "title": title,
                    "operation": operation,
                    "kind": kind,
                    "municipality": "Zapopan",
                    "neighborhood": neighborhood,
                    "price": price,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "parking": parking,
                    "furnished": furnished,
                    "accepts_pets": pets,
                    "near_schools": schools,
                    "published": True,
                    "description": "Propiedad ficticia para validar el primer incremento. No es una oferta comercial.",
                },
            )
            self.stdout.write(f"{reference}: {'creada' if created else 'ya existente'}")
