# Contratos entre módulos: Q241–Q271

Consolidación: 24 de octubre de 2026. Acuerdos de la conversación con Guillermo durante la etapa 5. Documento de diseño, sin implementación ni definición definitiva de nombres de funciones o esquemas de requests.

Complementa [Q215–Q240](acuerdos-q215-q240.md). Las reglas siguientes fueron aceptadas; los pendientes del final no se consideran resueltos.

## Inventario y búsqueda

**Q241:** un único módulo del backend concentra las reglas del inventario y ofrece una interfaz a CRM, website y herramientas del agente. Puede vivir dentro de Django, sin otro despliegue. El CRM solicita cambios autorizados; website y agente consultan. El módulo valida, aplica permisos y selecciona la información que puede devolver.

**Q242:** para los requisitos consultados distinguir cumple, no cumple y sin información. Un campo vacío no confirma ni niega una característica. Se pueden ofrecer alternativas pendientes de verificar, señalando qué falta confirmar. Si el prospecto solicita únicamente coincidencias confirmadas, excluir las que no permiten comprobar sus requisitos.

**Q243:** definir una ficha pública explícita para website y herramientas del agente. Características publicadas, precio, fotografías y condiciones autorizadas. Datos del propietario y notas internas solo para usuarios del CRM con permisos. El backend selecciona la información antes de enviarla al modelo.

**Q244:** una consulta exitosa sin coincidencias es un resultado distinto de una consulta fallida. No presentar una falla de base de datos como ausencia de propiedades ni completar resultados con información inventada o recordada por el modelo.

**Q245:** Haiku interpreta el mensaje y solicita la búsqueda mediante criterios estructurados permitidos. El código valida y ejecuta filtros. No aceptar SQL generado por el modelo. Preguntar por ambigüedades que cambien la búsqueda sin volver a pedir datos ya expresados.

**Q246:** proponer cambios concretos de filtros cuando sea necesario y esperar aceptación antes de ampliar la búsqueda. Identificar las alternativas como tales; no relajar presupuesto o requisitos silenciosamente.

**Q247:** presentar tres fichas simples inicialmente y permitir ver más con los mismos criterios. Limitar los resultados en el backend; no enviar todo el inventario a Haiku. El mecanismo concreto de paginación y el orden de resultados no quedaron especificados en esta ronda.

**Q248:** conservar los criterios vigentes como datos estructurados de la conversación en PostgreSQL. Una corrección explícita actualiza el criterio correspondiente sin perder los demás. Mantener el historial original. Una búsqueda anónima no identifica a la persona ni autoriza seguimiento.

## Agente y CRM

**Q249:** herramientas para operaciones concretas, como registrar interés, actualizar requisitos declarados y solicitar atención humana. Haiku solicita; el código valida condiciones y permisos, aplica cambios y devuelve resultados. No proporcionar una herramienta genérica para editar cualquier campo. Los resultados del módulo de agendamiento actualizan las citas del CRM.

**Q250:** registrar declaraciones como «ya di el anticipo» o «ya firmé» y avisar al asesor. Los hitos comerciales que requieren confirmación humana no se activan solo por una declaración del prospecto; el asesor los confirma desde el CRM.

**Q251:** una intención puede incluir varias propiedades. Preguntar por otra propiedad dentro de la misma búsqueda no crea otro ciclo ni reinicia los 28 días.

**Q252:** responsable de respaldo configurable en CRM, inicialmente Santiago o el líder designado, cuando no existe asesor asignado o el asignado fue desactivado. Registrar el interés bajo su responsabilidad y notificarle para resolver la asignación.

## CRM y notificaciones

**Q253:** si se registra el trabajo comercial y falla Telegram, conservar el registro y responsable. Reintentar únicamente la notificación, sin recrear prospecto, tarea ni cita. Registrar el error técnico en logs.

**Q254:** notificar eventos que requieren atención: nueva asignación, intervención humana solicitada, cita creada o modificada y declaración de un avance que deba confirmar el asesor. Las preferencias cotidianas quedan en CRM. Avisar también cuando el prospecto pida comunicar algo al asesor.

## Agendamiento

**Q255:** Haiku solicita cita con prospecto, propiedad y horario elegido. El código obtiene del CRM asesor asignado, calendario, duración y ventanas permitidas. El modelo no cambia libremente esas reglas.

**Q256:** los horarios ofrecidos son opciones, sin reserva. Al elegir uno, comprobar nuevamente condiciones antes de crear la cita. Si cambió la disponibilidad, explicar y ofrecer alternativas. Confirmar solo con resultado verificado de creación. La comprobación no constituye por sí sola una garantía de exclusión frente a ediciones externas del calendario.

**Q257:** partir de la cita registrada en CRM, vinculada con prospecto y referencia de Google Calendar. Comprobar solicitante y permisos. El prospecto puede modificar sus propias citas tras identificarlo mediante el mecanismo acordado; si la referencia es ambigua, preguntar cuál.

**Q258:** reprogramar como una única operación de negocio. Validar nuevo horario antes de modificar; coordinar calendario, CRM y notificación. El modelo no organiza por su cuenta cancelación seguida de creación. Verificar resultado desconocido antes de comunicar éxito o repetir.

**Q259:** registrar el intento antes de contactar al calendario y conservar una referencia que permita reconocerlo. Si calendario cambia y falla guardar el resultado en CRM, recuperar la misma operación y verificar lo ocurrido antes de crear otra cita. La transacción local no abarca Google Calendar. El asesor confirma en CRM si la visita ocurrió; el fin del horario no demuestra asistencia.

La forma exacta de referencia, exclusión de operaciones concurrentes, recuperación y estados técnicos internos queda por especificar. No se añaden por este motivo etapas comerciales al CRM.

## Seguimiento

**Q260, precisada en Q262:** el código determina destinatarios y fechas, comprobando autorización, día del ciclo, conversación activa, etapa comercial y control humano. Volver a comprobar pertinencia antes de enviar. El modelo no añade días ni reinicia ciclos; su redacción debe respetar el formato permitido por el canal.

**Q261:** omitir envíos que perdieron su día; no recuperarlos en un día excluido del calendario. Ejemplo: servicio apagado el día 5 y recuperado el 6, continuar el 7. Registrar omisión, conservar inicio del ciclo y no acumular mensajes. Días acordados: 1, 5, 7, 14, 18, 22, 26 y 28.

**Q262:** fuera de la ventana permitida de conversación de WhatsApp, usar plantilla aprobada y variables con datos validados. Evitar llamar al modelo por envío cuando completar la plantilla no lo requiera. Si no existe plantilla aprobada utilizable, registrar bloqueo para revisión, sin sustituir por texto libre fuera de ventana. Cuando el prospecto responde, Haiku continúa dentro de las reglas aplicables.

La política revisada permite texto libre dentro de las 24 horas del último mensaje del usuario y exige plantillas aprobadas fuera. No es el mismo reloj que los 28 días del ciclo comercial. [Política oficial consultada](https://business.whatsapp.com/policy).

## Recepción y envío

**Q263:** registrar el mensaje antes de programar su procesamiento. Conservar texto, canal, conversación e identificador para reconocerlo. Ante reintento de transporte del mismo mensaje, reutilizar el registro; no repetir modelo ni acciones por ese duplicado. Mensajes distintos con el mismo texto siguen siendo distintos. Website y WhatsApp alimentan el mismo flujo, conservando particularidades de canal. Se mantienen agrupación y un procesamiento activo por conversación.

**Q264:** persistir respuesta y destinatario antes de enviar. Si el resultado permite reintentar, retomar el envío sin generar otra respuesta. Comprobar vigencia y control del agente antes de enviarla.

**Q265:** un timeout no demuestra que el mensaje no salió. Verificar confirmaciones disponibles antes de reenviar. Si no se puede determinar qué ocurrió, registrar incertidumbre y generar atención pendiente para el asesor. No reenviar automáticamente una operación de resultado desconocido. Los estados técnicos del envío no cambian la etapa comercial.

## Contexto y procedimientos, Q266–Q271

**Q266:** construir por código el contexto pertinente a la conversación e intención correspondientes: criterios vigentes, estado comercial pertinente e instrucciones aprobadas. Consultar precios y horarios actuales mediante sus herramientas cuando se necesitan; un resumen no confirma esos datos ni hitos comerciales.

**Q267, corregida posteriormente en Q270–Q271:** se propuso resumir cuando hiciera falta conservando originales. Guillermo cuestionó la necesidad para conversaciones sencillas y aprobó posponer ese mecanismo en la primera versión.

**Q268:** procedimientos en archivos versionados junto con la aplicación. Santiago valida contenido comercial y Guillermo controla publicación. Conversaciones y resúmenes no modifican automáticamente procedimientos. Horarios y duración de citas continúan como configuración del CRM. Las instrucciones orientan al modelo; el código mantiene validaciones.

**Q269:** el código selecciona instrucciones según tarea y estado comercial confirmado. Cargar reglas comunes y procedimientos pertinentes sin otro modelo que decida su selección en esos casos.

**Q270–Q271, resolución vigente:** enviar el historial completo de la conversación correspondiente junto con instrucciones y datos pertinentes. Mantener criterios estructurados y CRM como estado vigente. Posponer resúmenes automáticos, compresión y un presupuesto propio de contexto. Registrar tokens, coste y latencia durante las pruebas; decidir con mediciones si esa complejidad llega a ser necesaria. Conservar el manejo de errores del proveedor acordado, sin prometer contexto ilimitado.

La [comparación de Hermes y Waku](../research/contexto-memoria-hermes-waku-2026-10-24.md) explica los mecanismos inspeccionados. Sus propuestas de compresión no forman parte del alcance inicial aprobado.

## Pendientes de especificación

- Esquemas de operaciones y resultados, límites y nombres definitivos de la interfaz.
- Orden y paginación del inventario; tratamiento concreto de requisitos geográficos que necesitan información adicional.
- Vinculación autorizada de identidad y conversación entre canales, conforme a decisiones previas.
- Atomicidad o recuperación entre recepción persistida y programación del trabajo.
- Identificadores de operaciones, deduplicación por canal y recuperación de resultados externos desconocidos.
- Tratamiento de concurrencia entre citas propias y cambios externos de Google Calendar.
- Confirmaciones disponibles en cada canal y límites reales de verificación del envío.
- Detalles de construcción del contexto completo y medición de uso; resúmenes y compresión pospuestos.

La lista identifica trabajo pendiente; no autoriza infraestructura adicional ni comenzar la etapa 6.
