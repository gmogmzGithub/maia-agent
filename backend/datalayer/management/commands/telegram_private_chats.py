import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Muestra IDs de chats privados iniciados con el bot; nunca imprime el token ni mensajes"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Configura TELEGRAM_BOT_TOKEN y reinicia backend y worker.")
        try:
            with httpx.Client(timeout=12, follow_redirects=False) as client:
                response = client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates",
                    json={"limit": 100, "timeout": 0, "allowed_updates": ["message"]},
                )
                result = response.json()
            if not result.get("ok"):
                raise CommandError(
                    "Telegram rechazó la consulta. Revisa el token y que el bot no tenga otro consumidor de updates."
                )
            chats = {}
            for update in result["result"]:
                chat = update.get("message", {}).get("chat", {})
                if chat.get("type") == "private":
                    chats[chat["id"]] = chat.get("username") or chat.get("first_name") or "Asesor"
            if not chats:
                self.stdout.write(
                    "Sin chats privados disponibles. El asesor debe abrir el bot y pulsar Iniciar."
                )
            for chat_id, name in chats.items():
                self.stdout.write(f"{name}: {chat_id}")
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"No se pudo consultar Telegram ({type(exc).__name__}).") from None
