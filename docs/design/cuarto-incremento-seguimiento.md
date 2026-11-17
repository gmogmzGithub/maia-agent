# Cuarto incremento: seguimiento de prospectos

Estado al 7 de noviembre de 2026: Guillermo confirmó que las pruebas del incremento funcionan. Quedan pendientes la aprobación y sincronización de plantillas, su activación y la validación del seguimiento real con ellas. El último estado documentado es PENDING; las plantillas permanecen desactivadas según ese registro. La [validación manual](../testing/cuarto-incremento.md) conserva evidencia y pendientes.

Guillermo priorizó el [incremento 6, captación de propiedades](sexto-incremento-captacion.md), mientras espera la aprobación de Meta. El incremento 5, acompañamiento posintención, queda pospuesto. Este cambio de orden no cierra el cuarto incremento ni declara el paso a Beta.

## Acuerdos previos

- Un ciclo de 28 días por intención. Responder o consultar otra propiedad no reinicia el ciclo.
- Enviar únicamente los días 1, 5, 7, 14, 18, 22, 26 y 28.
- Omitir envíos que pierden su día. No acumular ni recuperar mensajes en días excluidos.
- El código determina fechas y destinatarios y vuelve a comprobar pertinencia antes del envío.
- Conservar la atención entrante aunque termine el ciclo de seguimiento.
- Respetar las reglas del canal y la autorización de contacto. Tener un celular no acredita autorización.
- Fuera de la ventana permitida de WhatsApp, usar una plantilla aprobada utilizable; si falta, registrar bloqueo sin sustituirla por texto libre. Verificar las reglas vigentes de Meta durante el diseño técnico.

## Primera ronda aceptada

- **S1:** incluir recepción y envío de WhatsApp mediante Meta en este incremento. Reutilizar el harness y la cola existentes.
- **S2:** enviar inicialmente a las 11:00, hora de Guadalajara, configurable desde CRM. Revisar pendientes cada minuto sin alterar los días del ciclo.
- **S3:** suspender mensajes de prospección con cita agendada; omitirlos mientras el asesor mantenga a Maia pausada. Cerrar el ciclo ante Sin interés o solicitud de no recibir mensajes. Al reanudar, conservar inicio y días restantes, sin recuperar mensajes omitidos.

## Pendientes de validación

Los acuerdos funcionales y técnicos están registrados abajo. Falta comprobar aprobación, sincronización, activación y seguimiento real con plantillas. La confirmación general de Guillermo acredita las pruebas realizadas, sin marcar automáticamente cada casilla histórica. La entrega real pendiente impide cerrar el incremento.

## Segunda ronda aceptada

- **S4:** omitir el seguimiento del día si el prospecto escribió durante las últimas 24 horas en website o WhatsApp y podemos identificarlo. No posponer ni reiniciar el ciclo. Este umbral comercial no sustituye las reglas del canal.
- **S5, corregida por Guillermo:** activar por defecto el seguimiento de prospectos que llegan por WhatsApp mientras no hayan agendado cita, sujeto a las demás reglas de pertinencia y baja. Para contactos originados en website, solicitar permiso para escribir por WhatsApp. Verificar los requisitos vigentes de Meta antes de implementar; el origen WhatsApp no sustituye por sí solo cualquier requisito exigible de autorización.
- **S6:** el asesor confirma desde CRM una nueva intención después de una nueva interacción y tras terminar el ciclo anterior. No borrar historial ni reiniciar automáticamente por tiempo transcurrido. Una negativa a recibir mensajes requiere nuevo permiso explícito.

## Tercera ronda aceptada

- **S7:** desde website, contar el ciclo desde el interés inicial. Enviar solo después de obtener permiso y celular. Omitir los días anteriores sin reiniciar el reloj.
- **S8:** después de cancelar o realizar una visita, el asesor decide desde CRM si reactiva la prospección. Continuar solo con los días restantes del ciclo original. No reactivar automáticamente por terminar una visita.
- **S9:** contar días naturales, incluidos sábados, domingos y festivos, con envío inicial a las 11:00 de Guadalajara.

## Cuarta ronda

- **S10, corregida por Guillermo:** recuperar el historial y los requisitos pertinentes para retomar cada conversación con un mensaje breve y contextual. No usar un mensaje genérico idéntico para todos. Usar la skill `backend/agent/skills/comunicacion-cliente/SKILL.md` en toda comunicación con prospectos y clientes. La personalización no elimina las restricciones del canal.
- **S11:** evitar propiedades y precios en la plantilla inicial de reactivación. Al responder el prospecto, consultar inventario vigente antes de ofrecer propiedades. La reactivación puede apoyarse en requisitos declarados, sin afirmar disponibilidad actual.
- **S12:** mostrar inicio y fin del ciclo, próximo envío o suspensión, último intento y resultado, permiso o rechazo e historial en la conversación. No añadir etapas comerciales para resultados técnicos.

## Quinta ronda aceptada

- **S13:** diseñar plantillas de reactivación con referencias contextuales permitidas, como operación, tipo y zona. El código recupera datos pertinentes; el agente selecciona cómo retomar la conversación dentro del formato aprobado. La personalización exacta depende de aprobación de Meta. Cuando el prospecto responde, continuar con el contexto autorizado y la skill de comunicación, respetando las reglas del canal.

## Sexta ronda aceptada

- **S14:** permitir el envío durante una hora desde el horario configurado. Al recuperar el servicio dentro de esa ventana, volver a comprobar pertinencia antes de enviar. Fuera de ella, omitir ese día, sin acumular mensajes ni añadir otro ajuste al CRM.
- **S15:** personalizar con los datos útiles disponibles, sin exigir todos los requisitos. Si falta contexto útil o existen contradicciones que impiden redactar fielmente, omitir el envío y registrar revisión pendiente en CRM. No inventar preferencias ni sustituirlo por un saludo genérico.

## Séptima ronda aceptada

- **S16:** completar reservas desde WhatsApp mediante resumen y botón Confirmar visita. Cancelación y reprogramación también requieren acción explícita. Reutilizar validaciones de reserva separando la autorización de sesión web de la autorización por canal WhatsApp. El LLM no confirma reservas; un celular declarado en website no concede acceso a citas de otra conversación.
- **S17:** comenzar la integración WhatsApp con texto y botones. Posponer transcripción de audios. Ante un audio durante el piloto, pedir al prospecto que escriba el mensaje, sin interpretarlo.

## Octava ronda aceptada

- **S18:** dar prioridad a los mensajes entrantes y procesar un solo seguimiento a la vez, reutilizando la cola existente. No cargar todos los prospectos simultáneamente al LLM. La prioridad afecta la selección de trabajos pendientes; no interrumpe una llamada externa ya iniciada.
- **S19:** si Haiku propone una plantilla inexistente o datos sin respaldo, omitir ese envío y registrar el motivo para revisión en CRM. No reintentar automáticamente la redacción ni sustituirla por un mensaje genérico.

## Flujo técnico aceptado

1. El programador revisa cada minuto qué ciclos tienen un envío debido dentro de su ventana y registra un trabajo por prospecto y día del ciclo.
2. El worker vuelve a comprobar pertinencia, control humano, actividad reciente, permiso aplicable, citas y bajas antes de preparar el envío.
3. El código recupera el historial pertinente y los requisitos de la intención. Haiku usa ese contexto y la skill de comunicación para proponer una plantilla y sus datos contextuales, entre las alternativas aprobadas.
4. El código valida la propuesta contra el contrato de la plantilla, los datos de origen y las reglas del canal. Conserva el mensaje exacto antes de enviarlo.
5. Justo antes del envío, comprueba nuevamente si la persona respondió, agendó, rechazó mensajes o si el asesor pausó a Maia. Si perdió pertinencia, omite el envío.
6. El transporte WhatsApp registra el resultado y las confirmaciones disponibles. Un reintento de entrega no vuelve a llamar al modelo. Un resultado desconocido no provoca reenvío automático.

Este flujo no modifica los días del ciclo ni sustituye las plantillas aprobadas por texto libre.

## Arquitectura implementada

Reutilizar PostgreSQL y Procrastinate. Mantener un backend y el worker actual.

| Responsabilidad | Ubicación y comportamiento |
| --- | --- |
| Reglas y datos | `datalayer`: ciclo, intentos, elegibilidad, contexto autorizado y validación de propuestas. |
| Programación | `worker`: revisión cada minuto y trabajos por intento. Mayor prioridad para mensajes entrantes; un bloqueo compartido para seguimientos. |
| Redacción | `harness`: ejecución específica de seguimiento que reutiliza instrucciones, skill y trazas. No llamar directamente a `attend()`, que exige un mensaje entrante pendiente y admite herramientas comerciales. |
| Canal | `api`: validar e identificar eventos entrantes de WhatsApp. `worker`: enviar mensajes persistidos y registrar resultados. |
| Interfaz | `crm`: datos del ciclo, revisión y acciones humanas. Website conserva sus permisos por sesión. WhatsApp autoriza acciones desde su propio canal, no mediante un celular declarado en website. |

### Persistencia

- **Ciclo:** prospecto, intención y contexto de origen, inicio, cierre, suspensión y permiso aplicable. No borrar ciclos anteriores.
- **Intento:** ciclo y día, vencimiento, versión del contexto, plantilla y variables validadas, mensaje exacto, estado, referencia externa y error. Restricción única por ciclo y día.
- **Transporte WhatsApp:** referencias externas únicas para reconocer mensajes y confirmaciones repetidos. Guardar el mensaje entrante antes de encolar; guardar el saliente antes de enviar. Vincular la entrega al mensaje para reintentar sin volver a generar.

El trabajo se registra en la misma transacción corta que el intento. La restricción de datos evita recrear un envío aunque el trabajo anterior ya haya terminado; la deduplicación de la cola no basta por sí sola.

### Concurrencia y control humano

La versión instalada, Procrastinate 3.10.0, admite `priority`, `lock` y `queueing_lock`. Dar mayor prioridad a mensajes entrantes y usar un `lock` compartido por todos los seguimientos, con un `queueing_lock` distinto por intento. La prioridad ordena pendientes, sin interrumpir trabajos iniciados ni reservar puestos del worker.

Capturar una versión del contexto y volver a comprobarla antes del envío. Considerar mensajes identificados en ambos canales, cambios del asesor, bajas y citas pendientes o confirmadas. Las consultas y actualizaciones usan transacciones cortas; Haiku y Meta se llaman fuera de ellas.

Si algo cambia durante la generación, descartar la propuesta desactualizada. Sigue existiendo un intervalo entre la última comprobación y la aceptación externa del mensaje; no prometer cancelar un envío ya aceptado por Meta.

### Recuperación

Persistir el comienzo del envío antes del HTTP. Si se pierde la respuesta o el proceso cae sin conocer el resultado, conservar estado incierto y revisar confirmaciones disponibles. No reenviar automáticamente. Aplicar confirmaciones repetidas sin duplicar efectos y sin retroceder un resultado de entrega por eventos recibidos fuera de orden.

### Validación prevista

- Simular los 28 días sin esperarlos: días permitidos, hora, vencimientos y omisiones.
- Duplicar eventos y ejecutar dos programadores: un intento por ciclo y día.
- Responder, pausar o agendar durante la generación: descartar el envío que perdió pertinencia.
- Validar recuperación de contexto y aplicación de la skill, sin preferencias inventadas ni mezcla de conversaciones no autorizadas.
- Perder la respuesta del transporte: conservar incertidumbre y evitar duplicados.
- Probar texto, botones de citas, baja y seguimiento con el número del piloto y plantillas aprobadas.

## Preparación externa

Se usa el número de prueba de Meta en Maia App; la aplicación anterior se conserva y el número personal mantiene su uso. Webhook y recepción real están comprobados. La configuración y los textos presentados a Meta quedan en [WhatsApp del piloto](../testing/whatsapp-setup.md).

El 7 de noviembre las tres plantillas figuraban PENDING y desactivadas. Sincronizar antes de preparar una entrega controlada. No sustituirlas por texto libre fuera de la ventana del canal ni reactivar una baja para probar.

## Restricción de WhatsApp verificada

Consulta del 6 de noviembre de 2026: la [política de WhatsApp Business](https://business.whatsapp.com/policy), sección 2, exige plantillas aprobadas fuera de las 24 horas del último mensaje del usuario. El historial permite decidir qué retomar, pero no habilita enviar cualquier redacción libre fuera de ventana. La personalización selecciona una plantilla y completa sus variables con datos registrados; queda pendiente la aprobación de Meta. Una variable no contiene un mensaje arbitrario completo.

## Skill implementada

`agent/config.py` incorpora obligatoriamente `skills/comunicacion-cliente/SKILL.md` y `skills/comunicacion-humana/SKILL.md` al sistema del harness. Ambas se cargan en conversaciones y selección de seguimientos, sin elección del modelo. La primera conserva las reglas de estilo de Guillermo, contexto autorizado y hechos vigentes; la segunda añade un trato cercano, mensajes cortos y cancelaciones sin presión comercial. Para seguimientos se mantiene el límite de dos frases, 45 palabras y una pregunta. Los textos automáticos de citas se redactaron con las mismas reglas, sin una llamada adicional al modelo.

La evidencia actual y los comandos están en la [validación del cuarto incremento](../testing/cuarto-incremento.md). Los borradores aislados no acreditan entregas a prospectos.

## Mejoras transversales

- **Comunicación:** ambas skills se cargan siempre. Los textos fijos mantienen el mismo tono sin otra llamada al modelo; las plantillas conservan el cuerpo aprobado por Meta.
- **Propiedades:** introducción breve, hasta tres fichas y pregunta final. Conservar avisos de prueba y datos desconocidos. La corrección de duplicaciones se limita al texto de inventario y no repite acciones comerciales.
- **Citas y Telegram:** ofrecer horarios disponibles y exigir confirmación explícita. Los avisos distinguen evento y atención requerida, omiten campos vacíos y conservan propiedad y horario del evento al reintentar.
- **Nombre:** responder primero y preguntar amigablemente si falta, sin bloquear ni insistir. Guardar únicamente el nombre expresado. No iniciar intención ni modificar permisos al registrarlo; preservar aislamiento entre sesiones web.
- **Portada:** casa en lugar de estrella, sin rótulo geográfico, sugerencias progresivas cada tres segundos y acceso destacado al inventario. No alterar lo escrito; respetar movimiento reducido.
- **Inventario CRM:** publicar y despublicar desde cada fila; filtrar por texto, publicación, operación, tipo y municipio. Cambiar publicación sin sobrescribir otros campos ni cancelar citas. Filtros locales sobre el inventario cargado, sin paginación de servidor ni persistencia de filtros.
- **Enlaces:** dominio público del piloto para propiedades y CRM; CRM exige acceso del equipo.

La [matriz de regresiones por fase](../testing/mejoras-transversales.md) define recorridos, evidencia y pendientes. Estos ajustes no incorporan los incrementos 5 y 6.

### Presentación responsive aceptada

Guillermo aceptó tres fichas compactas por fila en escritorio, dos visibles en tablet y una con parte de la siguiente en móvil. La distribución depende del ancho disponible: un iPad horizontal puede mostrar tres. Una sola ficha conserva su tamaño compacto. El desplazamiento horizontal queda dentro del grupo, sin avance automático; historial vertical y campo de escritura accesible.

Las versiones conservan foto, nombre, zona, precio, recámaras, baños, estacionamientos, avisos y acciones. Los botones tienen al menos 44 px de altura. No se ocultan datos por usar móvil.

Las respuestas nuevas reservan los datos generales a la ficha y dejan solo introducción y siguiente paso útil. Una pregunta concreta recibe el dato solicitado; una comparación, las diferencias pertinentes. «Me interesa» no vuelve a enumerar la propiedad ni vuelve a pedir contacto conocido. El historial anterior conserva su texto, aunque sus fichas adoptan el tamaño nuevo. Aceptación del diseño no equivale a validación visual de la implementación.

Corrección acordada con Guillermo: pulsar «Me interesa» registra la selección y abre la atención hacia una visita, salvo que el cliente haya pedido otro paso. Aplica al chat, inventario y ficha pública. La acción no muestra un mensaje artificial del cliente ni repite la ficha. Si todavía no aparece en la conversación, la muestra una vez. Solo vuelve a presentarla ante una petición explícita. Maia propone horarios reales y pide únicamente datos faltantes; para el nombre usa «Por cierto, ¿con quién tengo el gusto?», una sola vez. No exige otro clic en Enviar, no reemplaza el borrador ni concede seguimiento, reserva o identidad. Un fallo conserva el reintento de la misma acción. El historial anterior no se reescribe.

### Conversación expandida aceptada

Al enviar el primer mensaje, el chat ocupa la altura disponible bajo una cabecera compacta. Desaparecen el título y la explicación iniciales; el campo cambia a «Continuemos la conversación…». Recargar una conversación existente restaura esta vista. «Nueva búsqueda» recupera la portada.

El historial, contacto, permisos, citas y avisos comparten el área vertical desplazable. El campo de escritura queda visible abajo. Escritorio centra el chat con ancho máximo de 1100 px; tablet y móvil aprovechan el espacio disponible. Las fichas conservan un ancho máximo de 300 px.

«Propiedades» muestra el inventario sin desmontar el chat. «Volver a la conversación» conserva historial, formularios y borrador durante ese cambio de vista. El borrador no se guarda al recargar la página. El hash permite abrir directamente el inventario aunque exista una conversación guardada.

En móvil, la vista sigue el tamaño y desplazamiento del viewport visual cuando cambia el teclado. Restaurar la conversación no enfoca el campo automáticamente. Validar teclado y orientación en dispositivos físicos antes de dar por aceptada esta parte.
