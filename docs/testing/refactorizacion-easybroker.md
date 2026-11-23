# Reorganización de EasyBroker

22 de noviembre de 2026. Análisis y corrección de tres hallazgos de arquitectura sobre los cambios recientes. Se conservan los ADR 0002/0003, las reglas comerciales y la aceptación real pendiente.

## Hallazgos corregidos

1. **Aceptación del mensaje público.** El turno coordinaba bloqueos, revisiones, tarjetas, texto y propuesta estructurada por separado. Un cambio de privacidad podía sustituir el texto y luego recuperar el original al validar una propuesta sin fichas. `public_history.accept_reply` concentra la decisión completa y descarta la propuesta anterior cuando cambia la información pública. `message_fields` prepara referencias y fuentes para guardar el mensaje de una vez, sin una actualización posterior desde la recepción del website.
2. **Sesión de revisión.** La presentación del CRM aceptaba respuestas tardías sin comprobar selección o página y agrupaba el guardado con las lecturas posteriores. `EasyBrokerReviewSession` ordena lecturas, descarta resultados de otra selección, evita doble envío y conserva una escritura confirmada si falla la actualización. React mantiene formularios, sondeo y presentación. No se crea un framework de sesiones ni un transporte nuevo.
3. **Ciclo de sincronización.** La generación, adquisición, aplicación, checkpoint y reintentos estaban repartidos entre conexiones, importaciones y worker. `datalayer/easybroker/sync.py` concentra ese protocolo mediante solicitud y operaciones de tomar/aceptar/fallar un lote. El worker conserva transporte y coordinación. La aplicación de una observación y la programación de su continuación se confirman juntas; si falla la cola, ambas se revierten. La caducidad permanece en las reglas de publicación.

## Verificación

Resultado: **347 pruebas de backend aprobadas, 2 omitidas**. Pruebas del frontend, incluidas las ocho de revisión de EasyBroker, tipos y compilación aprobados. Sin migraciones nuevas ni diferencias en OpenAPI.

- Pruebas integradas de respuesta estructurada y sin estructura, tanto en website como WhatsApp, después de ocultar un precio consultado sin tarjeta. Se comprueba texto persistido, presentación, continuidad y entrega en cola.
- Inserción de tarjetas importadas como referencias e incorporación de las fuentes a mensajes posteriores sin tarjeta.
- Pruebas del ciclo de sincronización desde su interfaz: trabajador antiguo rechazado, aceptación repetida, reintentos, un solo acceso remoto por lote, ausencia de HTTP dentro de transacciones y reversión de observación/checkpoint si falla la continuación.
- Ocho pruebas de la sesión del CRM: páginas fuera de orden, selección tardía, escritura confirmada seguida de lectura fallida, doble envío, revisiones de cuenta y ficha, error tardío de sondeo y detención de la sesión.
- Suite completa del backend, pruebas existentes del frontend, comprobación de tipos y compilación.
- OpenAPI exportado comparado sin diferencias; comprobación de Django, lint y detección de migraciones sin cambios de esquema.
- Proxy de la plataforma ya arrancada: creación y lectura de una conversación vacía, sin llamar al modelo. Esa comprobación valida los servicios existentes, no despliega esta reorganización.

No se modifican credenciales, instrucciones del agente ni datos existentes. No se conectan cuentas reales ni se activa la publicación de importaciones. El informe visual del análisis se genera en el directorio temporal del sistema, fuera del repositorio.
