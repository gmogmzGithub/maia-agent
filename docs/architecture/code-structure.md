# Organización del código

La plataforma mantiene una aplicación Next.js y un backend Django. Website y CRM comparten sesión, contrato REST y estilos. El worker ejecuta el mismo código Python en otro proceso. Las carpetas separan responsabilidades; no crean microservicios ni bases de datos adicionales.

El [diseño implementado de captación](captacion/README.md) documenta los modelos del incremento 6, el almacenamiento y acceso a imágenes, la revisión y los pendientes de durabilidad. Incluye un [diagrama interactivo](captacion/actual.html).

```text
frontend/
  src/
    main-website/
      pages/              Inicio y ficha pública de propiedad
      components/         Chat e inventario público
      conversation/       Sesión, adaptación al navegador y presentación de respuestas
    crm/
      pages/              Acceso y administración del inventario
      components/         Prospectos, conversaciones, avisos y configuración de asesores
      styles/             Estilos del CRM
    shared/
      components/         Cabecera y presentación de propiedades
      lib/                Cliente HTTP y tipos generados desde OpenAPI
      styles/             Estilos comunes
    app/                  Rutas y layout exigidos por Next.js

backend/
  api/                    Rutas REST, autenticación y sesiones HTTP
  agent/
    config.py             Carga de las instrucciones de ventas
    instructions/         Procedimientos e instrucciones versionados
    skills/               Skills del agente; comunicación con clientes cargada siempre
    tools.py              Herramientas que el modelo puede solicitar
  harness/
    runtime.py            Ciclo LLM, reintentos y presupuesto de tiempo
    tools.py              Ejecución y resultados de herramientas durante el turno
    memory/context.py     Historial y contexto temporal, sin consultas
    replies/              Aceptación pura y recuperación factual
    presentation/         Formato de fichas y WhatsApp, sin ORM ni red
  worker/
    dispatch.py           Programación, bloqueo y agrupación de trabajos
    tasks.py              Entrada del trabajo que ejecuta el harness
    telegram.py           Entrega privada, confirmación y resultados inciertos
  datalayer/
    models.py             Modelos persistentes
    schemas.py            Contratos de datos y validación
    inventory.py          Filtros, consultas y proyecciones públicas/privadas
    conversations.py      Mensajes, revisiones y recepción transaccional
    memory.py             Lectura autorizada de hechos, historial y continuidad
    turns.py              Adquisición y publicación transaccional del turno
    tool_actions.py       Operaciones comerciales de las herramientas
    replies.py            Hechos actuales y aceptación bajo bloqueo
    whatsapp_presentation.py Snapshot vigente para presentación del canal
    prospects.py          Captura, normalización, asignación y control humano
    crm.py                Proyecciones privadas para el equipo
    migrations/           Historial existente de Django
    management/           Comandos de administración
    admin.py              Inspección administrativa de los modelos
  llm_ops/
    executions.py         Registro de ejecuciones, tokens, herramientas y logs
  maia/                   Configuración, URLs y entradas ASGI/WSGI
  tests/                  Pruebas del comportamiento integrado
  scripts/                Comprobaciones contra la plataforma en ejecución
  core/                   Dos referencias históricas requeridas por la migración inicial
```

## Diferencia entre agente y harness

`agent` expresa el trabajo comercial: instrucciones de ventas y herramientas disponibles. `harness` ejecuta la conversación: llama a Haiku, procesa solicitudes de herramientas y aplica límites de ejecución. Los filtros y las escrituras se resuelven en `datalayer`; el modelo no ejecuta SQL.

`agent/config.py` incorpora siempre los cuerpos de `skills/comunicacion-cliente/SKILL.md` y `skills/comunicacion-humana/SKILL.md` a las instrucciones del sistema. La primera conserva precisión, contexto y concisión; la segunda añade un trato cercano. Su carga no depende de una elección del modelo. Tanto la conversación como la selección contextual de seguimiento usan ambas. Los textos automáticos siguen esas mismas reglas en su redacción fija; no llaman al modelo. Las plantillas de WhatsApp conservan el texto aprobado por Meta.

La sección «Atención natural» de `comunicacion-humana` añade reconocimiento contextual, una decisión principal por turno, reparación de errores y respeto a negativas y cierres. Los ejemplos son referencias, no respuestas fijas. La [investigación de comunicación](../research/comunicacion-humana-2026-11-07.md) registra fuentes, adaptación a Maia y límites de las muestras con Haiku.

`worker` decide cuándo ejecutar y evita trabajos concurrentes de una conversación. No interpreta al prospecto. `llm_ops` registra lo que ocurrió; sus estados técnicos no se convierten en estados comerciales del CRM.

## Recorrido de un mensaje

1. El chat de `main-website` llama a `api` mediante el cliente de `shared`.
2. `api` verifica sesión y entrada; `datalayer` guarda el mensaje.
3. `worker.dispatch` registra el trabajo dentro de la misma transacción del mensaje.
4. `worker.tasks` inicia `harness.runtime`.
5. El harness carga las instrucciones y herramientas de `agent`, recupera el historial mediante `datalayer` y llama al modelo sin mantener una transacción abierta.
6. Las herramientas consultan o actualizan datos mediante `datalayer`. `llm_ops` registra la ejecución dentro de las transacciones correspondientes.
7. El chat consulta el resultado y muestra texto y fichas.

## Compatibilidad de datos

El paquete Django ahora está en `datalayer`, pero conserva el identificador registrado `core`. Por eso las tablas, permisos, usuario autenticado, rutas del administrador y migraciones aplicadas mantienen sus nombres. `core/models.py` conserva solamente `UserManager` y `property_reference`, que la migración inicial importa por su ruta histórica. El código nuevo no debe importar ese archivo.

También se conservan los identificadores OpenAPI y el nombre registrado de la tarea `attend_conversation`, para que mover archivos no cambie el contrato HTTP ni invalide trabajos pendientes.

## Regla para código nuevo

Las pantallas del website pertenecen a `main-website`; las del equipo, a `crm`. Usa `shared` para piezas comunes, evitando mezclar allí reglas propias de una pantalla. `app` contiene las entradas del router, sin duplicar la implementación de las pantallas.

En Python, ubica instrucciones y catálogo de herramientas en `agent`, ejecución del modelo en `harness`, programación de trabajos en `worker`, consultas y transacciones en `datalayer`, métricas y trazas en `llm_ops`, y transporte HTTP en `api`. Crea subdivisiones cuando exista código que las necesite. No añadas interfaces, procesos o paquetes vacíos para funciones futuras.

## Segundo incremento

`api/prospects.py` separa operaciones públicas de contacto y operaciones privadas del CRM. La confirmación del celular pasa por una acción explícita del website, no por una afirmación del modelo. El teléfono agrupa fichas del CRM; la sesión del navegador sigue autorizando el acceso a cada conversación.

`datalayer/prospects.py` registra prospecto, eventos y avisos junto con sus trabajos pendientes en transacciones cortas. `worker/telegram.py` ejecuta HTTP después de confirmar esa transacción. Una entrega incierta no se reintenta; un aviso bloqueado o rechazado admite reintento desde el CRM.

Los requisitos siguen la conversación inicial hasta que el asesor los modifica. Las conversaciones posteriores con el mismo número se guardan por separado y no sobrescriben ni reciben ese contexto. El control de pausa invalida revisiones activas para impedir respuestas después de que el equipo toma el control.

## Tercer incremento

`datalayer/appointments.py` concentra ventanas, disponibilidad local, propuestas y operaciones de citas. Un bloqueo corto de configuración serializa las reservas del piloto; las operaciones persistentes conservan los horarios ocupados mientras Google responde o se verifica un resultado desconocido. No mantiene transacciones abiertas durante HTTP.

`worker/google_calendar.py` cifra credenciales, renueva acceso y ejecuta HTTP. `worker/appointments.py` crea, modifica, cancela, verifica y detecta cambios externos. Las tareas de mantenimiento usan la cola existente y se revisan cada minuto; las citas futuras se consultan cada cinco minutos.

`api/calendar_auth.py` vincula OAuth a la ficha del asesor y la sesión staff. La cuenta candidata requiere confirmación explícita. `api/appointments.py` separa operaciones privadas del CRM y confirmaciones del navegador propietario de la conversación. El número declarado nunca autoriza acceso a citas de otra sesión.

`datalayer/booking_tools.py` prepara propuestas para el website. El modelo no confirma reservas: el clic del prospecto o la acción explícita del asesor crea la operación. `crm/components/Appointments.tsx` configura reglas y gestiona citas; `CalendarConnect.tsx` gestiona conexiones. `main-website/components/VisitCard.tsx` muestra propuestas y resultados persistentes.

## Cuarto incremento

El piloto horario del 20 de noviembre usa `datalayer/followup_pilot.py` para registrar un permiso temporal y un ciclo acotado mediante `start_followup_pilot`. `FollowupCycle.pilot` es vacío para el calendario normal; únicamente el ciclo autorizado usa ocho intentos cada 30 minutos, silencio de cinco minutos y cobertura inicial de tres plantillas aprobadas. El mismo mantenimiento, worker y transporte ejecutan ambos perfiles. El cierre restaura la baja anterior y retira el permiso temporal. El CRM etiqueta estos intentos como pruebas, sin presentarlos como días transcurridos.

`datalayer/followups.py` concentra calendario, ciclos, permisos, contexto autorizado, elegibilidad e intentos únicos por ciclo y día. `harness/followups.py` realiza una sola selección contextual entre plantillas aprobadas; no ejecuta herramientas comerciales. `worker/followups.py` coordina generación, validación y entrega. Todos los seguimientos comparten un bloqueo de Procrastinate, con menor prioridad que mensajes entrantes.

`api/whatsapp.py` verifica firma y cuenta del webhook y guarda eventos antes de encolar. `datalayer/whatsapp.py` identifica remitentes del canal, deduplica eventos, aplica confirmaciones de entrega y prepara mensajes y botones. `worker/whatsapp.py` ejecuta HTTP fuera de transacciones, sincroniza plantillas y conserva resultados inciertos sin reenvío automático.

`api/followups.py` permite configurar hora y plantillas, registrar permiso desde website y gestionar ciclos desde CRM. `crm/components/Followups.tsx` muestra seguimiento y revisión sin añadir etapas comerciales. `ContactCard.tsx` obtiene permiso opcional de WhatsApp. La confirmación de propuestas reside en `datalayer/booking_tools.py`, compartida por website y WhatsApp, con autorización independiente por canal.

Las respuestas pendientes o rechazadas permanecen en CRM con su estado, pero no se presentan como mensajes enviados en el historial público ni en el contexto del agente. Un remitente autenticado de WhatsApp puede retomar el contexto de un seguimiento dirigido a él; otro navegador no recibe ese historial por declarar el mismo número.

`harness/presentation/properties.py` presenta fichas de propiedades en WhatsApp con datos del inventario. La skill de comunicación humana reserva la narración al agente y los datos de las fichas al canal. El website usa la versión compacta de `PropertyCard` en el chat y presenta énfasis como elementos de texto, sin interpretar HTML. Los avisos de citas conservan una instantánea en `Notification.payload._visit`; Telegram la mantiene al reintentar y solo envía los campos del proveedor.

La herramienta `record_name` delega en `datalayer/prospects.py`: guarda el nombre expresado sin iniciar una intención ni cambiar permisos. El harness recibe el nombre conocido para evitar preguntas repetidas. WhatsApp puede actualizar la ficha asociada al remitente; una sesión del website conserva su propio nombre sin sobrescribir una ficha compartida por declarar su celular.

`crm/components/PropertyInventory.tsx` presenta la tabla, filtros combinados sobre el inventario ya cargado y acciones de publicación. `PATCH /crm/properties/{id}/publication` cambia solo `published` bajo bloqueo de fila; comparte con el editor el aviso de despublicación con cita pendiente. El cambio no cancela citas ni sobrescribe otros campos.

### Fichas del chat: escritorio, tablet y móvil

`main-website/styles/chat-properties.css` usa consultas del contenedor del chat: desde 900 px muestra tres columnas; entre 560 y 899 px, dos; por debajo, una ficha y parte de la siguiente. Cada ficha mide como máximo 300 px y mantiene su ancho aunque esté sola. El umbral de tres columnas subió de 720 a 900 px al ampliar la conversación para conservar dos fichas en tablet vertical. El grupo admite desplazamiento horizontal manual y por teclado; el historial conserva desplazamiento vertical. `PropertyCard` aplica tamaños compactos solo en el chat y mantiene datos, avisos y acciones en todos los tamaños.

La acción «Me interesa» registra la selección sin una burbuja de texto fabricada. Comparte el transporte con el formulario, bloquea llamadas simultáneas y conserva el identificador para reintentar sin duplicar efectos. El clic no reemplaza un borrador existente. Los enlaces del inventario y ficha pública restauran primero sesión y conversación; el parámetro de entrada se elimina para no repetirlo al recargar.

`MessageInput.property_id` identifica el clic. `receive_message` comprueba publicación y registra interés, acción y trabajo en una transacción. La deduplicación precede a esos efectos. `Message.kind=property_interest` conserva la acción para el agente; `display_kind=hidden` la excluye del historial público. Si la ficha todavía no aparece, `display_kind=card` muestra únicamente su instantánea pública. La visibilidad persiste al recargar. Mensajes escritos y WhatsApp conservan su contrato HTTP.

`load_turn` entrega historial completo pertinente, fichas mostradas, selección, hechos y continuidad de la última respuesta elegible del canal. `harness/memory/context.py` construye el contexto autorizado sin otra llamada al modelo. El clic no fuerza horarios ni nombre: el agente elige cómo continuar y consulta `visit_slots` cuando corresponde. Consultar no reserva ni concede permisos. Una entrada posterior puede desplazar el propósito anterior.

El harness separa recuperación de presentación: filtra fichas ya mostradas tanto en búsquedas como en consultas de detalle. `get_property(show_again=true)` permite volver a mostrarlas cuando el cliente lo pide. Los datos siguen disponibles para responder preguntas. El nombre pertenece a la respuesta completa del agente; no se añade al terminar. `Conversation.name_requested` se conserva por compatibilidad histórica y deja de controlar el turno.

`get_property(show_card=false)` devuelve datos al modelo sin añadir otra ficha, para preguntas concretas y comparaciones. Las consultas de detalle con ficha actualizan la propiedad correspondiente sin reemplazar las otras opciones de la búsqueda.

`propose_reply` termina el loop con bloques ordenados de texto, propiedades y un control opcional, más propósito y pendiente. No ejecuta operaciones comerciales. `datalayer/replies.py` reúne hechos actuales bajo bloqueo; `harness/replies/validation.py` valida referencias, condiciones de contacto y propuesta de visita sin ORM. Las generaciones truncadas y los lotes que mezclan propuesta final con otras herramientas se rechazan antes de ejecutar sus llamadas.

Se permite una corrección de salida dentro del presupuesto existente. Esa corrección solo admite `propose_reply`, también por comprobación del código. No repite escrituras anteriores. Si falla, la recuperación conserva resultados comprobados sin afirmar que una operación ejecutada fracasó.

La migración `0007_message_reply_contract` añade `Message.presentation` y `Message.continuity`, opcionales para conservar mensajes anteriores. La continuidad incorpora revisión y mensaje entrante de origen; la fila del mensaje identifica la respuesta. No añade otra base de datos ni estados comerciales. Se guarda junto al mensaje bajo bloqueo y comprobación de revisión y pausa, sin mantener la transacción durante llamadas externas.

En WhatsApp solo las respuestas elegibles según entrega alimentan la continuidad. En cola, fallidas o inciertas no acreditan una pregunta presentada. Un callback de un mensaje antiguo no sustituye el contexto de otro posterior. Aceptación por Meta no equivale a lectura.

`Chat` renderiza los bloques del contrato, sin reordenar preguntas mediante regex. Los formularios se muestran dentro de la respuesta que los propuso y solo si siguen vigentes. Las visitas realizadas conservan su resumen; las preferencias del contacto quedan accesibles por separado. `structured_payload` construye WhatsApp desde los mismos bloques, sin adjuntar propuestas globales ni truncar silenciosamente. El formato anterior permanece para mensajes históricos y avisos fijos; esos avisos tampoco reciben botones implícitos.

Los eventos `reply_validation` registran aceptación, rechazo, corrección y continuidad breve en `Execution.tool_events`. No guardan razonamiento interno del modelo. El esquema valida estructura y referencias; la naturalidad necesita evaluación conversacional.

### Vista de conversación expandida

`main-website/pages/Home.tsx` conserva montados chat e inventario y coordina su visibilidad. `Chat` informa si contiene mensajes; el estado local conserva borrador y formularios al alternar vistas. `Header` permite interceptar «Propiedades» desde Home; otras pantallas conservan su navegación.

`main-website/styles/conversation-view.css` distribuye cabecera, historial flexible y campo de escritura en la altura disponible. Contacto, permisos, citas y errores están dentro del historial desplazable. Home escucha cambios de `visualViewport` y elimina los listeners al salir de la vista expandida. El backend, las sesiones y los contratos HTTP no cambian.


## Separación del harness y del chat

Los cuatro candidatos de la revisión están implementados. El [mapa de bloques y archivos](harness/code-map.md) documenta el recorrido y sus responsabilidades.

`datalayer/memory.py` concentra elegibilidad y alcance de las fuentes; no construye prompts ni registra ejecuciones. `harness/memory/context.py` convierte ese snapshot en working memory. PostgreSQL conserva mensajes y continuidad; no se añade otro almacén.

`harness/tools.py` conserva criterios, fichas disponibles y controles de recuperación por turno. `runtime.py` coordina el protocolo sin ramas por nombres de herramientas comerciales. Las escrituras se mantienen en `datalayer/tool_actions.py` y `booking_tools.py`.

`harness/replies/validation.py` recibe hechos explícitos; `harness/presentation/whatsapp.py` recibe una instantánea de visita y aplica formato y límites sin consultas. `datalayer/replies.py`, `whatsapp_presentation.py` y `turns.py` conservan lecturas actuales, autorización, bloqueos y publicación atómica. La revalidación al publicar es intencional.

`main-website/conversation/session.ts` concentra restauración, envío, idempotencia y polling. `useConversation.ts` conecta HTTP, almacenamiento y temporizadores con React; `Replies.tsx` presenta bloques y controles vigentes. `Chat.tsx` conserva composición visual, borrador mediante la sesión y scroll. Las respuestas tardías no restauran una búsqueda descartada ni reemplazan un resultado de formulario más reciente.

La separación usa funciones y una sesión con estado por conversación. No introduce clases por herramienta, repositorios del ORM ni paquetes para proveedores futuros.


## Sexto incremento: captación

`api/capture.py` transporta cuenta, solicitudes, archivos y revisión; `datalayer/capture_schemas.py` valida el formulario y `capture_catalog.py` comparte el catálogo. `datalayer/captures.py` concentra revisión, incorporación, aceptación versionada y vencimiento; `capture_assets.py` autoriza las mutaciones de archivos y `capture_media.py` normaliza imágenes sin publicar originales. La dirección privada no pasa a la proyección del inventario.

`worker/capture_delivery.py` entrega avisos durables por email o Telegram. `maintain_captures` usa la cola existente para vencimientos. Las consultas públicas comprueban la exclusividad vigente incluso antes del mantenimiento. Los resultados inciertos no se reenvían automáticamente.

`worker/capture_email.py` integra el transporte HTTPS de Resend y el HTML de correo; `api/capture_mail.py` verifica la firma del webhook. `datalayer/capture_mail.py` concentra configuración sin secretos, elegibilidad de reintentos y aplicación transaccional de eventos de entrega. `capture_contract.py` genera la copia PDF desde la aprobación o el acuerdo aceptado. Las herramientas administrativas `capture_mail_status` y `check_capture_storage` consultan sin enviar, modificar ni borrar datos.

`main-website/pages/OwnerCapture.tsx` implementa el recorrido de propietario y `OwnerAccount.tsx` su acceso. `crm/components/Captures.tsx` implementa revisión, correcciones y resolución de solicitudes. El mapa compartido vive en `shared/components/LocationMap.tsx`; tipos y transporte de captación están en `shared/lib/capture.ts`. Las entradas permanecen en `app`.

`shared/components/LocationFields.tsx` comparte el formulario de ubicación entre propietario y CRM; `shared/lib/google-maps.ts` carga Maps JavaScript una vez por página. `api/location.py` autoriza búsquedas/puntos y publica únicamente el punto permitido; `datalayer/google_locations.py` contiene el transporte Places, normalización mínima, cuotas y caché separada. `GoogleSearchSession`, `GoogleLocation` y `GoogleLocationUsage` no forman parte de los snapshots comerciales. La tarea `maintain_google_locations` limpia coordenadas vencidas y actualiza puntos automáticos sin cambiar contratos. Las fichas Google resuelven su mapa al visualizarlo; no almacenan coordenadas temporales en conversaciones.

Preventa se representa como condición de Venta; moneda, categorías y ubicación se amplían en el inventario existente. La migración `0008` conserva el identificador Django `core` y los datos anteriores. Las propiedades anteriores no requieren cuenta ni contrato nuevos.

`main-website/components/CaptureMedia.tsx` presenta zonas de arrastre separadas para fotos y planos. `hooks/useCaptureUploads.ts` conecta React, autorización y transporte; `lib/capture-upload-queue.ts` serializa la carga, reserva cupos y conserva el identificador de cada reintento. La cola solo vive en memoria y no entra a `sessionStorage`. El catálogo publica mínimo cinco/máximo veinte fotos y máximo cinco planos; el backend vuelve a verificar el máximo bajo bloqueo. `CaptureAsset.request_id` ya era único por captación y ahora se devuelve para reconciliar respuestas perdidas. No se añaden tablas ni se cambia el almacenamiento privado.

`shared/components/MoneyInput.tsx` comparte la captura de montos entre propietarios, inventario, presupuestos y opinión de valor. `shared/lib/money-input.ts` separa presentación con comas de la representación numérica: los formularios envían el valor sin separadores. Conserva hasta dos decimales, edición del cursor y validaciones de campos requeridos/mínimos. El prefijo visual muestra `MX$` o `US$` según la moneda del formulario; cambiar moneda no convierte ni modifica el monto. Un presupuesto sin moneda definida muestra `$`. Las cantidades no monetarias conservan sus controles numéricos.

`crm/lib/capture-status.ts` concentra la agrupación visual y el siguiente paso de captación; `crm/components/CaptureStatus.tsx` comparte las etiquetas entre lista y ficha. `crm/styles/captures.css` separa los estados de la selección y adapta la navegación lista/detalle a móvil. Los contadores usan captaciones, sin modificar el ciclo comercial ni el backend. [Validación y estados](../testing/captacion-estados-crm.md).


### Avisos de error y validación

`shared/components/ErrorFeedback.tsx` comparte el diálogo de errores en website y CRM. `app/layout.tsx` monta el proveedor; las pantallas conservan sus estados y presentan errores mediante `ErrorNotice`. El diálogo usa `<dialog>` nativo para mantener el foco y bloquear interacción detrás del aviso. No se cierra automáticamente. Una lista agrupa campos inválidos, permite ir a cualquiera y conserva el mensaje junto al control. Los errores iguales pendientes se agrupan; los mensajes informativos y éxitos siguen en la pantalla.

El proveedor escucha `invalid` en captura, evita los globos nativos y agrupa la validación HTML, incluidos montos con `setCustomValidity`. Conserva y restaura los atributos de accesibilidad de los campos. Solo se ofrecen reintentos que la pantalla declara explícitamente: lecturas y la cola idempotente de archivos. No se repiten automáticamente aprobaciones, contratos, publicaciones ni envíos. Los fallos de Maps/Places usan el mismo aviso, separados de las notas informativas.

En las correcciones del CRM, `.capture-grid > .full` hace que ubicación ocupe la fila completa. El formulario compartido conserva dos columnas interiores en escritorio y una en móvil. No cambia datos, autorización ni contratos HTTP. [Pruebas de avisos y ubicación](../testing/avisos-errores-ubicacion.md).


## Consolidación de la captación · 16 de noviembre de 2026

Se mantienen la organización, los identificadores, permisos, estados y acuerdos existentes. Las cinco mejoras concentran coordinación dentro de los módulos actuales:

- `datalayer/capture_approval.py` contiene la representación comercial duradera y la correspondencia entre una solicitud aprobada y la copia de contrato. Contrato, aceptación, reintento y entrega comparten esa decisión. `google_locations.commercial_data` conserva su import histórico como compatibilidad.
- `shared/lib/location-editing.ts` concentra sesión de búsqueda, invalidación, punto privado, confirmación y descarte de respuestas tardías. `LocationFields.tsx` adapta React, teclado y presentación; mantiene sus props y la política de confirmación del CRM. Google y el mantenimiento de referencias temporales no cambian.
- `main-website/lib/owner-capture-journey.ts` concentra arranque autorizado, recuperación, verificación, continuación tras cuenta, exclusión de acciones simultáneas, guardado con revisión y descarte de resultados de otra cuenta/solicitud. La pantalla conserva presentación y almacenamiento del borrador; la cola de archivos mantiene su responsabilidad.
- `shared/lib/form-feedback.ts` concentra la validación HTML y los fallos remotos, asociación con controles, agrupación, anotaciones accesibles, foco, cierre y reintento explícito. `ErrorFeedback.tsx` adapta React y el diálogo nativo. `api-errors.ts` conserva identidad de campos y estado de respuesta. La respuesta existente `detail` se conserva; se añade opcionalmente `errors: [{message, code, field?}]`, sin modificar los estados HTTP. Los montos identifican su control visible para evitar enfocar el valor oculto del formulario.
- `crm/lib/capture-review-session.ts` concentra listado, selección, acciones y reconciliación. Una escritura confirmada sigue confirmada aunque falle la lectura posterior; resultados de otra selección o revisión más antigua no reemplazan el estado vigente. El backend sigue siendo la autoridad de revisión y publicación.

Las pruebas cruzan las mismas interfaces de los módulos que utiliza la presentación. El feedback se prueba además con DOM real mediante jsdom, únicamente como dependencia de desarrollo. [Validación de la consolidación](../testing/refactorizacion-incremento-6.md).
