# Seguimiento con plantillas: prueba completa del piloto

Preparado el 16 de noviembre de 2026. Actualizado el 20: piloto horario iniciado por autorización explícita de Guillermo. Véanse [operación continua](operacion-continua-mac.md) y [evidencia del incremento 4](cuarto-incremento.md).

**Cierre aceptado, 20 de noviembre:** Guillermo confirmó que las pruebas de mensajes resultaron bien. Las tres plantillas iniciales y los cinco seguimientos posteriores se recibieron; los cinco de la repetición quedaron `read`. Se comprobó selección entre plantillas y cambio de variables hacia Tepatitlán tras una respuesta del usuario. El ciclo 5 cerró automáticamente a las **21:37**, retiró el permiso y restauró la baja. Comprobado a las 22:07, sin próximo intento. Queda aceptada la prueba técnica comprimida; los fallos originales, el calendario natural de 28 días y los pendientes comerciales/operativos conservan su alcance separado. Los estados siguientes se mantienen como evidencia cronológica.

**Estado a las 21:11 del 20 de noviembre:** el ciclo 4 terminó con tres entregas correctas y cinco fallidas porque el token había vencido a las 20:00. No se considera aprobada la secuencia completa. Tras actualizar y verificar el token (válido hasta las 23:00), el ciclo **5** repite únicamente esos cinco envíos, con previsión 21:12/21:17/21:22/21:27/21:32 y cierre hacia las 21:37. Se conservan los registros anteriores y el silencio mínimo de dos minutos. El registro detallado y las nuevas protecciones están en la sección más reciente del cuarto incremento.

**Contenido comercial pendiente:** Guillermo confirmó funcionamiento técnico, pero rechazó la calidad de las plantillas como seguimiento. Santiago definirá el contenido de sus reemplazos en una revisión posterior. El piloto actual no acredita aceptación comercial de los textos; no se cambian durante esta prueba.

## Piloto horario iniciado el 20 de noviembre

**Cambio autorizado a las 20:21:** Guillermo pidió acortar los cinco intentos restantes a intervalos de **cinco minutos** y silencio mínimo de **dos minutos**. Se aplicó `accelerate_followup_pilot --cycle 4`, conservando los tres intentos leídos, el inicio, el destinatario y la restauración de la baja. Nuevo calendario previsto: **20:22:44, 20:27:44, 20:32:44, 20:37:44 y 20:42:44**; cierre a las **20:47:44**, hora de Guadalajara. El mantenimiento por minuto puede ejecutar cada paso en el minuto siguiente. Esta modificación reemplaza el calendario original de los cinco intentos pendientes que aparece abajo.

El ajuste persiste en los metadatos del ciclo; no requiere otra migración. Solo reprograma intentos sin ejecutar, rechaza intentos en preparación y no pospone las fechas al repetir el comando. La ventana de envío baja a cinco minutos. Los ciclos normales siguen usando sus días y 24 horas de silencio. El CRM muestra los valores vigentes del piloto.

Guillermo autorizó reactivar su número personal, probar las tres plantillas y comprimir los días a horas. Se creó el ciclo **4** sobre su conversación WhatsApp existente a las **18:47**, hora de Guadalajara. No se falsificó un mensaje entrante ni se alteraron fechas de ciclos anteriores. Su búsqueda vigente en WhatsApp es departamento en renta, hasta MX$25,000, dos recámaras, mascotas y Zapopan; se usó para esta nueva intención de prueba.

| Intento | Hora local prevista, 20 de noviembre | Plantilla |
| --- | --- | --- |
| 1 | 18:52 | `maia_retomar_operacion` |
| 2 | 19:22 | `maia_retomar_municipio` |
| 3 | 19:52 | `maia_retomar_tipo_municipio` |
| 4 | 20:22 | Selección contextual |
| 5 | 20:52 | Selección contextual |
| 6 | 21:22 | Selección contextual |
| 7 | 21:52 | Selección contextual |
| 8 | 22:22 | Selección contextual |

El mantenimiento normal del worker corre cada minuto; las horas son aproximadas. Cada intento vence a los diez minutos y no se recupera fuera de su ventana. Cierre y retirada del permiso temporal a las **22:32**. El estado previo de baja se restaura al cerrar; también se puede pedir baja antes desde WhatsApp o CRM.

Este perfil persiste en `FollowupCycle.pilot`, mediante la migración aditiva `0013`. Solo el comando explícito `start_followup_pilot --phone <número> --consent` lo inicia. Es idempotente mientras el piloto sigue abierto. El destinatario queda fijado y se comprueba en cada intento. Los ciclos normales conservan días y silencio de 24 horas.

En el piloto, el silencio mínimo baja a cinco minutos. La cita histórica del 9 de noviembre se conserva sin cambios y no suspende esta prueba; una cita vigente o nueva sí la suspende. También se conservan pausa, falta de permiso, baja, comprobación de cambios durante generación, estados de entrega y deduplicación. Las tres plantillas deben seguir aprobadas. Se habilitan como opciones **solo dentro de este piloto**; no se activan globalmente para otros prospectos.

Los tres primeros intentos restringen las opciones a una plantilla distinta para acreditar cobertura. Los siguientes permiten que Haiku elija entre las tres según el contexto. Todos pasan por mantenimiento → cola → selección → transporte → webhook → CRM. No se ejecuta manualmente el envío.

Pruebas observadas y resultados se registrarán en la sección más reciente del cuarto incremento. Este calendario comprimido valida la operación real en horas; no equivale a observar 28 días naturales.

## Preparación original para el calendario normal

## Evidencia ya obtenida

Las tres plantillas de Maia están aprobadas en Meta y sincronizadas, con variables revisadas. Guillermo autorizó un mensaje puntual a su número personal: se entregó, respondió y Maia continuó; ambas salidas llegaron a `read` y quedaron en CRM. Pasaron 60 pruebas aisladas de seguimiento y una de selección con Haiku real. Eso no acredita todavía entregas automáticas en días posteriores.

## Preparación del caso real

1. Acordar un caso identificado como PRUEBA, el destinatario y su permiso para recibir la secuencia. La autorización del mensaje puntual anterior no reactiva el seguimiento del número de Guillermo.
2. Registrar una intención nueva con búsqueda, contacto y permiso explícito desde el flujo normal. Conservar la historia previa. El caso debe estar sin baja, pausa ni citas pendientes; no cancelar citas o cambiar fechas de prospectos existentes para forzar la prueba.
3. Habilitar las tres plantillas acordadas y comprobar en CRM los datos que completan sus variables. Ahora siguen desactivadas.
4. Registrar ID de conversación, prospecto y ciclo; inicio, hora local, próximo intento y plantillas habilitadas. Confirmar que ningún otro caso sin permiso se vuelve elegible.

Solo `maia_retomar_operacion` tiene entrega real comprobada. Antes de iniciar la secuencia, acordar textos concretos y probar también `maia_retomar_municipio` y `maia_retomar_tipo_municipio`, registrando entrega y variables correctas. Un selector contextual puede elegir la misma plantilla varias veces; observar un ciclo no garantiza probar las tres.

Si se elige el número personal de Guillermo, requiere una decisión explícita de nuevo permiso y revisar los bloqueos de su ficha antes de comenzar. Actualmente conserva baja y ningún ciclo abierto. Este documento no cambia esos estados.

## Recorrido de varios días

La hora configurada es **11:00 de Guadalajara**, con ventana hasta las 12:00. Los días del ciclo son **1, 5, 7, 14, 18, 22, 26 y 28**, contados desde la fecha de inicio en esa zona horaria. Registrar las fechas concretas cuando se cree el caso, sin manipular el reloj ni las fechas de la base activa.

Para probar una primera entrega en el día 1 a las 11:00, iniciar el caso antes de las 11:00 del día anterior y no enviar nuevos mensajes durante las 24 horas previas al intento. Si se inicia esta noche, el intento de mañana a las 11:00 debe omitirse por actividad reciente: no es un fallo de entrega. Un día omitido no se recupera con un mensaje tardío.

| Momento | Acción y evidencia esperada |
| --- | --- |
| Día 0 | Completar búsqueda y permiso. Registrar contexto y siguiente intento; no debe haber envío inmediato de seguimiento. |
| Día 1 | Sin actividad reciente ni bloqueos, comprobar creación automática de un intento, selección de una plantilla con datos registrados, entrega y registro en CRM. No ejecutar el envío manualmente. |
| Después de la entrega | Responder en WhatsApp y comprobar continuación contextual. Registrar eventos y estados. |
| Día 5 | Sin interacción en las 24 h anteriores, comprobar una segunda selección y entrega automática. Acredita continuidad en un día posterior. |
| Días restantes | Registrar selección, entrega u omisión justificada por cada día. Repetir mantenimiento o recibir callbacks repetidos no debe duplicar mensajes. |
| Baja | Pedir dejar de recibir mensajes. Confirmar baja y cierre del ciclo. Una consulta posterior recibe atención sin reabrirlo. Los días posteriores no deben producir seguimientos. |

Las pruebas de baja, citas y pausa pueden cerrar o suspender la secuencia. Planificar su orden y usar casos separados autorizados si se necesitan comprobar los ocho envíos y también todas las interrupciones. No reabrir automáticamente el mismo ciclo para completar una lista de pruebas.

## Registro por intento y cierre

Registrar fecha prevista y real, día del ciclo, intento, plantilla, texto completado, estado de Meta, respuesta del destinatario, omisión o error, y evidencia en CRM. No guardar secretos ni tokens. Un `sent` solo prueba aceptación por Meta; exigir `delivered` o `read` para acreditar recepción.

La prueba queda aprobada cuando se comprueben el inicio normal con permiso, al menos dos entregas automáticas en días distintos, respuestas y continuidad, baja efectiva, omisiones previstas y ausencia de duplicados. Registrar aparte qué días reales se observaron y cuáles solo se cubrieron en pruebas aisladas. No declarar observados los 28 días antes de que transcurran.
