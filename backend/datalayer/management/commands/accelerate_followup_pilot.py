import json

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand, CommandError

from datalayer.followup_pilot import accelerate_pilot
from datalayer.followups import DAYS, cycle_days, due_date, end_date
from worker.whatsapp import WhatsAppError, check_credentials


class Command(BaseCommand):
    help = "Acorta los intentos pendientes del piloto: cada cinco minutos, silencio de dos."

    def add_arguments(self, parser):
        parser.add_argument("--cycle", required=True, type=int)

    def handle(self, *args, **options):
        try:
            check_credentials()
            cycle = accelerate_pilot(options["cycle"])
        except (ObjectDoesNotExist, ValidationError, WhatsAppError) as exc:
            raise CommandError(str(exc)) from exc
        completed = set(cycle.attempts.values_list("day", flat=True))
        self.stdout.write(
            json.dumps(
                {
                    "cycle": cycle.pk,
                    "ends_at": end_date(cycle).isoformat(),
                    "remaining": [
                        {"attempt": DAYS.index(day) + 1, "due_at": due_date(cycle, day).isoformat()}
                        for day in cycle_days(cycle)
                        if day not in completed
                    ],
                },
                indent=2,
            )
        )
