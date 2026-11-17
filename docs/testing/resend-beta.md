# Resend para BETA

Preparación del incremento 6. El 15 de noviembre de 2026 se verificó `maia.elmenlabs.com` en Resend: estado **Verified**, Forge **Ready**. Guillermo completó el asistente y se activó Resend en backend y worker, con configuración y webhook preparados según `capture_mail_status`. Guillermo confirmó que funciona el envío real de aprobación. Falta registrar explícitamente PDF, liga y evento `delivered` según la [guía de cierre](cierre-incremento-6.md#t06-correo-pdf-y-liga).

DNS confirmado en Cloudflare: TXT `resend._domainkey.maia.elmenlabs.com` para DKIM, CNAME `rsend.maia.elmenlabs.com` hacia `rsend.forge.rmta.net` y CNAME `send.maia.elmenlabs.com` hacia `send.forge.rmta.net`. Ambos CNAME usan DNS Only. Se conservó el túnel de `sandbox.elmenlabs.com`; no se modificaron los MX existentes. Recepción y seguimiento permanecen desactivados en Resend.

## Activación guiada

Desde la raíz del proyecto:

```bash
./scripts/setup-resend-beta.sh
```

El asistente abre las páginas de Resend, explica las acciones y captura las claves sin mostrarlas. Guarda únicamente `.local/resend.env`, con permisos privados y fuera de Git. No lee ni modifica el archivo de configuración principal del proyecto. No activa servicios, acepta contratos, paga ni envía mensajes.

Sus tres pasos son verificar un dominio y elegir remitente, crear una clave de envío limitada a ese dominio y configurar el webhook de entrega. Necesitas acceso a tu cuenta de Resend y al DNS del dominio. No habilites recepción ni cambies los MX del correo existente para enviar avisos. Conserva desactivado el seguimiento de aperturas y clics para los enlaces de acceso.

La URL de webhook del piloto es `https://sandbox.elmenlabs.com/api/capture/mail/webhook`. Debe seguir siendo accesible mediante HTTPS. Si cambia el dominio, ajusta también `PUBLIC_BASE_URL` del backend y worker para que los correos lleven a la instancia correcta.

Al terminar, activa de forma explícita el archivo adicional:

```bash
docker compose -f compose.yaml -f compose.resend.yaml up -d --no-deps backend worker
docker compose -f compose.yaml -f compose.resend.yaml exec -T backend python manage.py capture_mail_status
```

El segundo comando muestra configuración y conteos sin enviar ni revelar claves. `ready` solo confirma presencia y formato básico de configuración, no que Resend haya verificado el dominio ni aceptado el remitente. El archivo adicional conserva la configuración de base, base de datos y volúmenes. Usa ambos archivos al actualizar esos servicios para mantener Resend activado.

El asistente se comprobó con `bash -n` y análisis estático; no se ejecutó el recorrido que abre la cuenta y pide claves. La sesión de desarrollo usa Bash 5. No hay secretos reales en el asistente ni en el archivo adicional de despliegue.

## Primer envío

En CRM → Captación, abre la solicitud aprobada. El aviso guardado localmente admite «Enviar correo con el proveedor configurado» cuando el backend está preparado. La acción encola ese aviso sin cambiar la revisión, aceptar el acuerdo ni publicar la propiedad. No hay envío masivo automático de correos guardados.

Comprueba recepción del correo, adjunto PDF, versión, propietario y liga. Sin sesión, la liga debe pedir acceso y después abrir el acuerdo correcto. Con otra cuenta, el backend debe negar acceso. No aceptes el dummy en nombre del cliente para probar el envío.

En «Actividad y avisos», `sent` significa que el proveedor aceptó el mensaje; `delivered`, que el servidor del destinatario lo recibió, sin garantizar bandeja de entrada o lectura. Se distinguen demora, rebote, bloqueo y queja. Los resultados inciertos no admiten reenvío automático ni manual desde ese botón. Un fallo conocido antes de aceptar el envío sí permite reintentar. Los rebotes, quejas y supresiones requieren revisión, no insistencia.

## Contrato y seguridad del transporte

`CAPTURE_EMAIL_PROVIDER=resend` utiliza HTTPS, `RESEND_API_KEY` autentica el envío y `DEFAULT_FROM_EMAIL` identifica el remitente. Los adjuntos se envían como contenido Base64; no se publican en una URL externa. Cada intento autorizado lleva una clave de idempotencia por aviso e intento. Un resultado HTTP ambiguo permanece incierto; nunca se interpreta como rechazo seguro para volver a enviar.

`RESEND_WEBHOOK_SECRET` valida HMAC-SHA256 de los bytes originales y los encabezados Svix con tolerancia de cinco minutos. Los eventos se deduplican y solo guardan identificadores, tipo y fecha, sin contenido, destinatarios ni tokens. Un evento firmado puede llegar antes de la respuesta HTTP y recuperar una entrega pendiente de confirmar. Un `sent` o una demora tardíos no sustituyen una entrega confirmada.

El proveedor también maneja verificaciones y recuperación de cuenta, mediante la cola existente. La verificación de posesión del celular sigue pendiente en la etapa posterior; no se simula con Resend.

## Referencias del proveedor

- [Dominio verificado y separación del correo transaccional](https://resend.com/docs/dashboard/domains/introduction).
- [Claves de API y restricciones por dominio](https://resend.com/docs/dashboard/api-keys/introduction).
- [Envío HTTPS y adjuntos](https://resend.com/docs/api-reference/emails/send-email).
- [Idempotencia de 24 horas](https://resend.com/docs/dashboard/emails/idempotency-keys).
- [Creación y verificación del webhook](https://resend.com/docs/webhooks/create-webhook), [protocolo de firma](https://docs.svix.com/receiving/verifying-payloads/how-manual).

Los límites del plan y la aprobación de cuenta o dominio los decide Resend. El código no los omite ni acredita entrega real sin la prueba anterior.
