# Maia

Pre-Alpha para una inmobiliaria: inventario en CRM, búsqueda conversacional y fichas públicas. Consulta [`docs/architecture/code-structure.md`](docs/architecture/code-structure.md) para conocer los módulos.

## Estado de las pruebas

El plan manual está en Obsidian: `Testing Fase 1.md` y `Testing Fase 2.md`, dentro de `Projects/maia-real-estate`. Guillermo validó inventario y búsqueda, prospectos y citas. Confirmó que las pruebas del cuarto incremento funcionan. Quedan pendientes la aprobación de plantillas por Meta y la validación del seguimiento real con ellas. Mientras tanto, priorizó el [incremento 6, captación de propiedades](docs/design/sexto-incremento-captacion.md). El incremento 5, acompañamiento posintención, queda pospuesto.

Consulta las [mejoras y regresiones por fase](docs/testing/mejoras-transversales.md), la [validación del cuarto incremento](docs/testing/cuarto-incremento.md) y los [criterios de fases](docs/design/acuerdos-q215-q240.md#5-criterios-de-fases). Portada, nombre y filtros del CRM conservan pendientes de aceptación manual.

Captación: [retomar pruebas desde la #5](docs/testing/sexto-incremento-recorrido-manual.md). Para activar sugerencias y mapa Google, usar la [guía de Google Maps/Places](docs/testing/google-ubicacion-beta.md); sus claves se preparan con `scripts/setup-google-maps-beta.sh`, sin modificar la configuración principal.

## Opción recomendada: ejecutar todo con Docker

Requisito: Docker Desktop en ejecución. Ejecuta los comandos desde cualquier subdirectorio del repositorio. La primera línea te lleva a su raíz, así no importa si la terminal ya está dentro de `backend` o `frontend`.

1. Desde la raíz del repositorio, crea `.env` solo si aún no existe y configura tu clave de Anthropic. Sin esa clave, el CRM funciona, pero el chat no puede responder.

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   test -f .env || cp .env.example .env
   ```

   Si `.env` ya existe, conserva ese archivo y edítalo para configurar `ANTHROPIC_API_KEY`; no vuelvas a copiar la plantilla encima.

2. Construye e inicia PostgreSQL, backend, worker y website:

   ```sh
   docker compose up --build -d
   docker compose ps
   ```

   Espera a que `db` y `backend` aparezcan como saludables y los servicios `worker` y `web` como activos.

3. Crea tu acceso del CRM. No hay una cuenta ni contraseña predeterminadas. El comando te pide correo y contraseña; usa esos mismos datos al entrar al CRM.

   ```sh
   docker compose exec backend python manage.py createsuperuser
   ```

4. Abre:

   - Website: <http://localhost:3000>
   - CRM: <http://localhost:3000/crm>
   - Panel de ejecuciones: <http://localhost:8000/admin/core/execution/>

   Inicia sesión en el CRM con el correo y la contraseña que acabas de crear.

Para ver los registros de backend y worker mientras pruebas:

```sh
cd "$(git rev-parse --show-toplevel)"
docker compose logs -f backend worker
```

## Alternativa: ejecutar backend y website fuera de Docker

Requisitos: Docker, Python 3.13 con `uv`, Node.js 22 y `pnpm` 11. No inicies esta opción si ya estás usando todos los servicios con Docker, porque ocuparían los mismos puertos.

1. Desde cualquier subdirectorio, vuelve a la raíz del repositorio. Si aún no existe `.env`, copia la plantilla; configura `ANTHROPIC_API_KEY` en ese archivo.

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   test -f .env || cp .env.example .env
   ```

   Si `.env` ya existe, no lo sobrescribas.

2. Inicia PostgreSQL:

   ```sh
   docker compose up -d db
   ```

3. En la primera terminal, desde la raíz, instala dependencias, prepara la base, crea tu acceso y arranca el backend:

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   uv sync --project backend --frozen
   uv run --project backend --directory backend python manage.py migrate
   uv run --project backend --directory backend python manage.py createsuperuser
   uv run --project backend --directory backend python manage.py runserver 127.0.0.1:8000 --noreload
   ```

   Mantén esta terminal abierta. Si un comando falla, detente y resuelve ese error antes de ejecutar el siguiente.

4. En una segunda terminal, inicia el worker:

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   uv run --project backend --directory backend python manage.py procrastinate worker --concurrency=4
   ```

5. En una tercera terminal, instala dependencias del website y arráncalo:

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   pnpm --dir frontend install --frozen-lockfile
   pnpm --dir frontend dev
   ```

Abre las mismas direcciones de la opción Docker. Para entrar al CRM usa el correo y contraseña creados en el paso 3.

## Prueba manual del primer incremento

Usa datos ficticios claramente identificados con `PRUEBA`. En el CRM crea propiedades con estos grupos:

- **Resultados esperados:** al menos cuatro propiedades publicadas que coincidan con la misma operación, municipio, presupuesto y características. Esto permite validar “más opciones” sin resultados repetidos.
- **Exclusiones:** una propiedad sin publicar y una publicada cuyo precio quede fuera del presupuesto de la búsqueda.
- **Dato desconocido:** una propiedad con una característica relevante sin confirmar. Deja esa característica vacía si el formulario lo permite.
- **Privacidad:** agrega a una propiedad una nota interna identificable, por ejemplo `PRUEBA: no mostrar en respuestas públicas`.

Recorre los checks del primer incremento en este orden:

1. Crea una propiedad identificada como `PRUEBA`, guarda el formulario y vuelve a abrirla. Comprueba que conservó los campos.
2. Edita un dato, guarda y haz una nueva consulta en el chat. Comprueba que aparece el dato actualizado.
3. Publícala. Confirma que aparece en el inventario público y abre su ficha.
4. En el chat, busca usando operación, municipio, presupuesto y características. Comprueba que cada opción cumple los filtros.
5. Inicia otra conversación con una petición general. Maia debe preguntar los requisitos que faltan.
6. Cambia solo un requisito. Comprueba que la búsqueda lo aplica y conserva los demás.
7. Pide más opciones. Comprueba que muestra la siguiente página sin repetir propiedades ni cambiar los requisitos.
8. Busca una combinación sin resultados. Maia debe decirlo sin inventar propiedades ni relajar los filtros.
9. Pregunta por una característica desconocida. Maia debe marcarla como pendiente de confirmar.
10. Recarga el mismo navegador. Comprueba que conserva conversación y criterios.
11. Revisa respuestas y fichas. Confirma que no exponen la nota interna ni afirman datos que no estén en el inventario.
12. Despublica la propiedad. Confirma que desaparece de búsquedas nuevas y que su ficha pública queda inaccesible; los mensajes anteriores deben conservar lo que mostraron.
13. Revisa el panel `/admin/core/execution/` o los registros de backend y worker. Deben mostrar estado, herramientas, duración, tokens y errores cuando ocurran.

El comando opcional siguiente crea cuatro propiedades `PRUEBA`, todas publicadas. Tres son de renta y una de venta. No crea un borrador, por lo que tendrás que crear manualmente un borrador y suficientes propiedades coincidentes para tu filtro. No reemplaza los datos que ya existan.

```sh
cd "$(git rev-parse --show-toplevel)"
docker compose exec backend python manage.py seed_demo
```

En la opción local, usa en su lugar:

```sh
cd "$(git rev-parse --show-toplevel)"
uv run --project backend --directory backend python manage.py seed_demo
```

## Segundo incremento: prospectos y Telegram

El [diseño aceptado](docs/design/segundo-incremento-prospectos.md) define el alcance. En CRM → Asesores, configura el equipo, selecciona un asesor predeterminado y asigna responsables desde los editores de propiedades.

Para Telegram:

1. Crea un bot con `@BotFather` y guarda el token en `TELEGRAM_BOT_TOKEN` dentro de `.env`.
2. Configura `PUBLIC_BASE_URL` con una dirección del website que pueda abrir el asesor. `http://localhost:3000` solo funciona en la misma computadora.
3. Recarga el entorno de backend y worker:

   ```sh
   docker compose up -d --force-recreate backend worker
   ```

4. Cada asesor abre el bot en su conversación privada y pulsa **Iniciar**. Consulta los IDs sin imprimir token ni mensajes:

   ```sh
   docker compose exec backend python manage.py telegram_private_chats
   ```

5. Guarda el ID del chat privado en CRM → Asesores.

Los avisos se conservan aunque falte configuración. Desde su conversación en el CRM puedes reintentar avisos bloqueados o rechazados después de corregir la causa. Los avisos entregados o de resultado incierto no se reenvían. La [API de Telegram](https://core.telegram.org/bots/api#making-requests) distingue respuestas de éxito y error; un timeout de red no demuestra que no se entregó el mensaje.

El celular es declarado, sin SMS ni verificación de identidad. Cada visitante conserva acceso únicamente a su conversación. El CRM conserva una ficha por número normalizado. Los requisitos del primer contacto se actualizan desde su conversación hasta que el equipo los edita en el CRM; las conversaciones nuevas con el mismo número no los sobrescriben ni reciben el contexto de otras sesiones.

Pausar a Maia conserva mensajes e invalida respuestas en proceso. Reactivarla permite responder al siguiente mensaje; no envía automáticamente respuestas atrasadas. El asesor controla el estado comercial y el siguiente paso.

Una solicitud humana pendiente genera un solo aviso. Cuando el asesor cambia el estado a En atención, se da por atendida esa solicitud; una petición posterior puede generar otro aviso.

## Tercer incremento: citas

CRM → Citas permite configurar reglas globales, ventanas y duración por propiedad, crear citas y revisar cambios externos. CRM → Asesores conecta el calendario principal mediante OAuth y confirmación de cuenta.

Configura [Google Calendar](docs/testing/google-calendar-setup.md) antes de probar reservas reales. Backend y worker necesitan `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` y `CALENDAR_ENCRYPTION_KEY`. El [diseño aceptado](docs/design/tercer-incremento-citas.md) y la [validación manual](docs/testing/tercer-incremento.md) describen el alcance. Tercer incremento cerrado: Guillermo reportó las pruebas manuales exitosas y confirmó la corrección que ofrece horarios disponibles sin pedir primero una fecha.

## Cuarto incremento: WhatsApp y seguimiento

Pruebas realizadas aprobadas por Guillermo el 7 de noviembre de 2026. Pendientes: aprobación y sincronización de plantillas, activación y validación del seguimiento real mediante entrega controlada. El [diseño aceptado](docs/design/cuarto-incremento-seguimiento.md), la [configuración de WhatsApp](docs/testing/whatsapp-setup.md) y la [lista de pruebas](docs/testing/cuarto-incremento.md) describen el alcance y los pasos externos.

CRM → Prospectos → WhatsApp y reglas de seguimiento configura la hora, sincroniza plantillas aprobadas y muestra entregas que requieren revisión. La ficha de cada prospecto conserva ciclo, permisos y resultados. El website pide permiso para seguimiento; WhatsApp admite texto y botones de confirmación de citas. La transcripción queda para una incorporación posterior.

El código controla los días 1, 5, 7, 14, 18, 22, 26 y 28. Haiku selecciona la plantilla contextual con historial y requisitos; el transporte conserva el mensaje y sus resultados. Una respuesta reciente, cita, pausa, baja o vencimiento impide el envío. No se reenvían automáticamente resultados inciertos.

## Sexto incremento: captación de propiedades

Implementado en código y pendiente de aceptación manual. El propietario usa `/propietarios` para registrar Venta, Renta o Preventa; el equipo revisa desde CRM → Captación. La cuenta requiere email, teléfono y contraseña, y email verificado antes del envío. Cinco fotos mínimas con optimización automática, planos y enlaces opcionales. La publicación exige revisión y aceptación del contrato dummy de exclusividad por seis meses.

La aprobación y la preparación de renovación generan un correo con el contrato dummy PDF y una liga directa a la solicitud. Si hace falta iniciar sesión, el destino se conserva y después se enfoca el acuerdo. Recibir el PDF o abrir la liga no acepta el contrato. El [diseño de captación](docs/architecture/captacion/README.md) documenta la copia versionada y el control de entregas.

Consulta la [puesta en servicio y validación](docs/testing/sexto-incremento.md): requiere actualizar los tres procesos, aplicar las migraciones nuevas y configurar correo para verificación y recuperación reales. Por defecto, los correos se guardan como archivos privados de desarrollo. El inventario preexistente conserva su flujo.

Resend está preparado por HTTPS para los correos de cuenta y captación. La [guía de activación BETA](docs/testing/resend-beta.md) incluye un asistente para dominio, remitente, claves y webhook. No se activa automáticamente. El CRM distingue correo local, aceptado, entregado al servidor del destinatario, demorado y rebotado, y permite enviar el aviso local una vez configurado el proveedor.

Guillermo confirmó que pudo continuar con la verificación local. Quedan ajustes visuales y de la solicitud de cuenta, registrados en [mejoras transversales](docs/testing/mejoras-transversales.md#m22-diseño-de-captación). El [flujo completo de cuentas y verificación real de email y celular](docs/design/cuentas-y-verificacion.md) queda para otra etapa. La validación funcional de captación continúa.

## Checks todavía planeados

El incremento 5, acompañamiento posintención, permanece pospuesto y sin implementar. El cuarto conserva los pendientes de Meta y seguimiento real. El sexto necesita aceptación manual tras su puesta en servicio.

## Desarrollo y verificaciones automatizadas

Desde la raíz del repositorio:

```sh
uv run --project backend --directory backend pytest -q
uv run --project backend --directory backend ruff check .
uv run --project backend --directory backend python manage.py check
uv run --project backend --directory backend python manage.py makemigrations --check --dry-run
uv run --project backend --directory backend python manage.py export_openapi > frontend/openapi.json
pnpm --dir frontend api:generate
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Con el backend local y el website en ejecución, comprueba el proxy:

```sh
cd "$(git rev-parse --show-toplevel)"
uv run --project backend --directory backend python scripts/check_web_routes.py
```

La comprobación crea una conversación vacía y valida URL, cookies y protección CSRF; no llama al modelo. La búsqueda filtra por precio, municipio, colonia y características. La colonia se compara como texto, sin radios geográficos; las fotos se guardan como URLs.
