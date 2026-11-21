# WhatsApp del piloto

Estado: primer texto real recibido, procesado y vinculado al prospecto en CRM. Haiku generó una respuesta y Meta confirmó `delivered` el 7 de noviembre de 2026. Guillermo validó creación, reprogramación y cancelación de citas. La baja quedó registrada; su regresión y el seguimiento real con plantillas conservan pendientes en la [lista de validación](cuarto-incremento.md).

Usaremos el número de prueba de Meta en `Maia App` (`1123980987048265`). Basic falló en `real-estate-lead-agent`; la aplicación anterior se conserva. Meta muestra el mismo número de prueba y los mismos identificadores en la nueva aplicación. El número personal de Guillermo conserva su uso actual.

El túnel `maia-sandbox` apunta a `http://127.0.0.1:3000`. El endpoint público `/api/health` respondió HTTP 200. Para arrancar el túnel manualmente:

```sh
cloudflared tunnel --config ~/.cloudflared/config.yml run maia-sandbox
```

El callback verificado es `https://sandbox.elmenlabs.com/api/whatsapp/webhook`. El 7 de noviembre de 2026 se comprobó el desafío público con HTTP 200, el token válido de Maia App y la correspondencia de su secreto. Meta activó `messages` en v27.0. La suscripción de Maia App a la cuenta se creó mediante `POST /{WABA-ID}/subscribed_apps` y se confirmó mediante GET.

El panel advierte que una app sin publicar solo recibe eventos de prueba del panel. Sin embargo, la prueba con el número de prueba recibió el mensaje real y sus confirmaciones de entrega. Ese resultado no acredita recepción con un número de producción ni sustituye los requisitos de publicación.

## Valores locales

Configura en `.env`, sin compartir valores en el chat:

| Variable | Origen |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | Token autorizado para enviar mensajes y consultar las plantillas de la cuenta. Un token temporal sirve para probar, pero caduca. |
| `WHATSAPP_PHONE_NUMBER_ID` | Identificador del número del piloto en WhatsApp Cloud API, no el número telefónico. |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Identificador de la cuenta WhatsApp Business que contiene el número y las plantillas. |
| `WHATSAPP_API_VERSION` | Versión de Graph API habilitada para la aplicación, con formato `vNN.0`. No se presupone una versión. |
| `META_APP_SECRET` | Secreto de la aplicación Meta, usado para verificar firmas de webhooks. |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Cadena secreta elegida por Guillermo para verificar el alta del webhook. No es el token de acceso de Meta. |
| `PUBLIC_BASE_URL` | URL pública del website para los enlaces de propiedades. |

Consulta los [ejemplos oficiales de Meta](https://github.com/fbsamples/whatsapp-api-examples) y la [colección oficial de Cloud API](https://www.postman.com/meta/whatsapp-business-platform/overview).

## Aplicación, número y webhook

1. Abre la aplicación de Meta que gestionará el número del piloto y habilita WhatsApp Cloud API. Si usas el número de prueba de Meta, registra el destinatario de prueba en Meta antes de enviar.
2. Obtén los identificadores, token, versión y secreto anteriores. Para operación continua usa credenciales con los permisos y duración adecuados para la cuenta; evita depender del token temporal de la pantalla de prueba.
3. Publica la aplicación local con el túnel HTTPS de Cloudflare. La URL pública debe llevar `/api/whatsapp/webhook` al backend mediante el proxy del website.
4. Configura esa URL como callback de WhatsApp. Usa el mismo verify token que guardaste localmente y suscribe el campo `messages` de la cuenta correspondiente.
5. Reinicia backend y worker para cargar las credenciales: `docker compose up -d --force-recreate backend worker`.
6. Envía un texto desde tu WhatsApp al número del piloto. Comprueba en CRM la conversación con canal WhatsApp, su respuesta y el estado de entrega.

El webhook verifica la firma con el secreto de la aplicación y acepta solo la cuenta y el identificador de número configurados. Un GET de verificación exitoso no acredita recepción de POST firmados ni permisos para enviar.

## Plantillas contextuales

Actualización del 16 de noviembre de 2026, 20:00 (America/Mexico_City): credencial renovada y cargada tras recrear backend/worker con los proveedores de correo y mapas conservados. La sincronización real recuperó ocho plantillas; las tres de Maia constan como `APPROVED`, idioma `es_MX`, con sus variables originales y `enabled=False`. Falta acordar destinatario/texto y validar la entrega controlada antes de habilitar el seguimiento. No se enviaron mensajes ni se reactivaron ciclos.

Consulta del 16 de noviembre de 2026: Meta rechazó la lectura del catálogo con HTTP 401, código `190`, subcódigo `463` (token caducado). Hace falta renovar la credencial antes de comprobar aprobación y sincronizar. El CRM conserva `PENDING` del 7 de noviembre para las tres plantillas de Maia, todas desactivadas; no representa una consulta vigente de Meta. No se enviaron mensajes ni se reactivó el seguimiento.

El 7 de noviembre de 2026 se crearon estas tres plantillas con los textos aprobados por Guillermo, idioma `es_MX` y categoría solicitada `MARKETING`. Meta respondió `PENDING` para las tres. Se sincronizaron al CRM con las variables configuradas y `enabled=False`; no se enviaron mensajes.

| Nombre | Texto aprobado | Variables del CRM |
| --- | --- | --- |
| `maia_retomar_tipo_municipio` | Retomo tu búsqueda de {{1}} en {{2}}. ¿Quieres revisar opciones o ajustar lo que buscas? | 1: `kind`, 2: `municipality` |
| `maia_retomar_municipio` | ¿Seguimos buscando en {{1}} o prefieres revisar otra zona? | 1: `municipality` |
| `maia_retomar_operacion` | Sobre tu búsqueda para {{1}}, ¿quieres revisar opciones o cambió lo que necesitas? | 1: `operation` |

Pendiente: volver a sincronizar para comprobar la decisión de Meta y preparar una prueba controlada antes de activar los envíos. La baja actual de Guillermo se conserva.

1. Crea en Meta plantillas de seguimiento con cuerpo textual y variables numeradas, sin encabezados, multimedia, botones ni pie de página para esta primera integración.
2. Ejemplo de cuerpo para presentar a revisión de Meta: «Retomo tu búsqueda de {{1}} para {{2}} en {{3}}. ¿Quieres que revisemos opciones?».
3. Solicita la categoría que corresponda a reactivación comercial. No declares una plantilla de utilidad para evitar restricciones de marketing. La clasificación y aprobación corresponden a Meta.
4. Cuando estén aprobadas, abre CRM → Prospectos → WhatsApp y reglas de seguimiento → Sincronizar plantillas de Meta.
5. Asigna variables, por ejemplo: `1 → Tipo de inmueble`, `2 → Comprar o rentar`, `3 → Colonia` o `Municipio`. Activa cada plantilla que deba poder seleccionar Maia.
6. Incluye alternativas para búsquedas con pocos datos. El sistema omite el envío si no puede completar fielmente una plantilla aprobada; no inventa requisitos.

El modelo selecciona entre textos completados con datos registrados. No reescribe el cuerpo aprobado ni coloca un mensaje arbitrario completo en una variable. Si una plantilla cambia de estado en Meta, vuelve a sincronizar; los rechazos del transporte quedan visibles en CRM.

## Comprobaciones

- Número mexicano: Meta puede entregar el remitente con `521`. Maia conserva ese identificador del canal, usa `52` para identificar al prospecto y enviar, y reconoce confirmaciones en ambos formatos. El primer mensaje real permitió reproducir un rechazo de validación y el error de envío 131030 por esta diferencia. Tras corregirlos, se reprocesó el mensaje y se entregó una sola respuesta. Regresión: 132 pruebas aprobadas y una prueba real optativa de Haiku omitida.
- Texto entrante, respuesta contextual y propiedades con enlaces públicos.
- Resumen y botón de confirmación de cita dentro de WhatsApp; comprobar resultado en Google y CRM.
- Audio: solicitar texto, sin transcripción.
- Solicitud de baja: detener el seguimiento sin impedir nuevas consultas.
- Website: conservar sesión privada y pedir permiso de seguimiento por WhatsApp.
- Reactivación real fuera de la ventana de conversación con una plantilla aprobada y un destinatario autorizado.

No edites las fechas de prospectos reales para forzar envíos. Usa datos identificados como PRUEBA y acuerda el destinatario antes de una prueba de entrega real. Revisa ejecuciones con `docker compose logs -f backend worker`; los secretos y el contenido del webhook no se imprimen en los logs de aplicación.
