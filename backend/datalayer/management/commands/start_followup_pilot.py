import json

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand, CommandError

from datalayer.followup_pilot import start_pilot
from datalayer.followups import DAYS, PILOT_TEMPLATES, due_date, end_date


class Command(BaseCommand):
    help = "Inicia la prueba horaria acotada para un único número con permiso explícito."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--consent", action="store_true", required=True)

    def handle(self, *args, **options):
        try:
            cycle, created = start_pilot(options["phone"])
        except (ObjectDoesNotExist, ValidationError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "cycle_id": cycle.pk,
                    "created": created,
                    "started_at": cycle.started_at.isoformat(),
                    "ends_at": end_date(cycle).isoformat(),
                    "schedule": [
                        {
                            "attempt": index + 1,
                            "day_key": day,
                            "due_at": due_date(cycle, day).isoformat(),
                            "template": PILOT_TEMPLATES[index] if index < 3 else "contextual",
                        }
                        for index, day in enumerate(DAYS)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
