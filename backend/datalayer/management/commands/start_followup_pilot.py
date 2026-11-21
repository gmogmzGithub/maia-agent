import json

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand, CommandError

from datalayer.followup_pilot import start_pilot
from datalayer.followups import DAYS, PILOT_TEMPLATES, cycle_days, due_date, end_date
from worker.whatsapp import WhatsAppError, check_credentials


class Command(BaseCommand):
    help = "Inicia la prueba horaria acotada para un único número con permiso explícito."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--consent", action="store_true", required=True)
        parser.add_argument("--retry-failed-cycle", type=int)

    def handle(self, *args, **options):
        try:
            check_credentials()
            cycle, created = start_pilot(
                options["phone"], retry_cycle_id=options["retry_failed_cycle"]
            )
        except (ObjectDoesNotExist, ValidationError, WhatsAppError) as exc:
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
                            "attempt": DAYS.index(day) + 1,
                            "day_key": day,
                            "due_at": due_date(cycle, day).isoformat(),
                            "template": PILOT_TEMPLATES[DAYS.index(day)]
                            if DAYS.index(day) < 3
                            else "contextual",
                        }
                        for day in cycle_days(cycle)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
