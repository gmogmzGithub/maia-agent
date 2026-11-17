# Validación manual del segundo incremento

Resultado al 6 de noviembre de 2026: Guillermo confirmó que todas las pruebas fueron exitosas. Los casos siguientes quedan validados según su reporte. Telegram aceptó el mensaje de prueba y Guillermo confirmó su recepción.

Usa datos identificados como PRUEBA. Configura asesores, asesor predeterminado y chats privados en el CRM. Arranca backend, worker y website con `docker compose up --build -d`.

## Captura y CRM

- [x] Busca propiedades sin proporcionar celular. La búsqueda debe funcionar.
- [x] Pulsa Me interesa en una ficha. Envía el mensaje preparado y continúa en el website.
- [x] Proporciona un celular. Maia debe ofrecer revisarlo; todavía no debe existir una ficha nueva.
- [x] Corrige el número si hace falta y pulsa Confirmar mi número. La ficha debe aparecer una sola vez en CRM → Prospectos, con nombre opcional, requisitos, propiedad y asesor responsable.
- [x] Confirma de nuevo o recarga. No debe duplicarse la ficha ni el mismo aviso.
- [x] Cambia requisitos en la conversación inicial. Deben actualizarse en el CRM. Una corrección posterior del asesor queda bajo su control y no debe sobrescribirse por otro cambio automático.
- [x] Cambia estado, siguiente paso y responsable desde el CRM. Comprueba los valores guardados y el historial de cambios.

## Asignación e identidad

- [x] Elige una propiedad con asesor. Debe recibir la ficha y el aviso.
- [x] Solicita atención sin elegir propiedad. Debe asignarse al asesor predeterminado.
- [x] Expresa interés en propiedades de dos asesores. Debe conservarse el responsable de la primera.
- [x] Abre otro navegador o una ventana privada y registra el mismo celular. Debe conservarse una ficha, su responsable, estado y requisitos anteriores. La conversación nueva debe verse en esa ficha, con identidad sin verificar.
- [x] Desde el segundo navegador, recarga y continúa. No deben aparecer mensajes ni requisitos privados de la otra sesión.

## Control humano

- [x] Cambia a En atención. Maia debe seguir respondiendo.
- [x] Activa Pausar atención automática. Envía un mensaje: debe guardarse, generar aviso al asesor y no recibir respuesta automática.
- [x] Pausa mientras Maia prepara una respuesta. La respuesta pendiente no debe publicarse después de aplicar la pausa.
- [x] Desactiva la pausa y envía otro mensaje. Maia debe responder. La reactivación no envía respuestas atrasadas por sí sola.
- [x] Pide un asesor y rechaza dar el celular. La solicitud debe aparecer en el CRM y avisar por Telegram con celular no proporcionado. Puedes seguir buscando sin compartirlo.

## Telegram

- [x] Comprueba avisos privados por nuevo prospecto, solicitud humana, nuevo interés de un contacto que regresa y mensaje recibido con Maia pausada.
- [x] Cada aviso debe incluir motivo, resumen, contacto disponible, propiedad y enlace que abre su conversación en el CRM después de iniciar sesión.
- [x] Revisa que no avise por cada mensaje ordinario ni cambie el estado a En atención por enviar una notificación.
- [x] Quita temporalmente la configuración del chat de un asesor de prueba y provoca un aviso. Debe conservarse en el CRM como bloqueado. Corrige el chat y reintenta: debe entregarse una sola vez.
- [x] Un chat de grupo debe rechazarse. Un resultado incierto debe pedir revisión de Telegram y no permitir reenvío automático.

Las pruebas automatizadas cubren el timeout de entrega sin provocar envíos reales duplicados. Para revisar ejecuciones: `docker compose logs -f backend worker`.

Citas, WhatsApp y ciclo de seguimiento de 28 días quedan fuera de esta validación.
