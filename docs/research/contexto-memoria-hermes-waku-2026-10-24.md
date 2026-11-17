# Contexto y memoria: comparación de Hermes y Waku

Inspección: 24 de octubre de 2026. Etapa 5, diseño. Lectura estática de fuentes locales; no se ejecutaron los agentes, pruebas, instalaciones ni llamadas a modelos. No se modificaron los repositorios de referencia.

Referencias inspeccionadas, con árbol limpio al consultar:

- Hermes: `/Users/el-men/Workspace/hermes-agent`, HEAD `ccc695635094d7615373db267b77f894d978b1a0`.
- Waku: `/Users/el-men/Workspace/waku-agent`, HEAD `4b69b321324750f231fdfd72a83b38ad7301dcc3`.

Las observaciones describen esas revisiones, no una garantía de ejecución ni rendimiento. Las propuestas para Maia al final necesitan aprobación.

Revisión del 7 de noviembre de 2026: se volvió a inspeccionar el código local. Los HEAD de Hermes y Waku siguen coincidiendo con los anteriores. Se añadió el inventario actual de Maia y el detalle de carga, recuperación y alcance al final. No se consultaron bases de datos en ejecución ni memorias personales.

**Decisión posterior vigente, Q270–Q271:** Guillermo aprobó usar el historial completo de la conversación pertinente y posponer resúmenes automáticos, compresión y un presupuesto propio de contexto. Las propuestas de resumen de este informe son referencias para una necesidad futura demostrada, no requisitos de la primera versión. Véanse los [acuerdos actualizados](../design/contratos-q241-q265.md).

## Memoria funcional y persistencia cumplen responsabilidades distintas

La persistencia conserva información. La memoria funcional comprende cómo seleccionamos, actualizamos y recuperamos información para continuar una tarea. El contexto de trabajo es la selección concreta que enviamos al modelo en una llamada.

No necesitamos una base distinta para cada responsabilidad. PostgreSQL puede conservar mensajes, criterios vigentes, resúmenes y referencias a procedimientos; el módulo que construye contexto decide qué incluir y con qué alcance. El inventario y el CRM conservan sus reglas y operaciones autorizadas.

| Tipo | Ejemplo en Maia | Función |
|---|---|---|
| Historial original | «Hasta cuarenta mil; mejor treinta y cinco» | Conservar lo dicho y su orden. |
| Datos estructurados vigentes | Presupuesto máximo actual: 35,000 MXN mensuales | Aplicar la búsqueda sin reinterpretar todo el historial. |
| Resumen derivado | «Busca renta en Zapopan y corrigió su presupuesto» | Reducir contexto cuando haga falta; puede omitir información. |
| Procedimientos | Cómo ofrecer una visita y cuándo solicitar intervención humana | Orientar el comportamiento mediante instrucciones aprobadas. |
| Contexto de trabajo | Instrucciones, criterios, mensajes recientes y resultados pertinentes | Informar una ejecución concreta de Haiku. |

Un resumen puede estar bien redactado y contener un error. Un campo de preferencias expresa lo declarado por el prospecto; un anticipo confirmado requiere el procedimiento humano acordado. La autoridad depende del tipo de dato.

## Qué hace Hermes

Hermes separa mensajes de la memoria curada. `MemoryStore` mantiene `MEMORY.md` y `USER.md`; prepara una instantánea para el system prompt distinta de las listas vivas que persiste. Actualizar memoria no implica reescribir inmediatamente todo el prefijo de la sesión. [MemoryStore](/Users/el-men/Workspace/hermes-agent/tools/memory_tool_store.py:175).

El turno copia el historial que recibe, añade el mensaje nuevo y utiliza el system prompt de la sesión. El modelo ve los mensajes preparados para esa ejecución, no todo el contenido almacenado de forma automática. [Construcción del turno](/Users/el-men/Workspace/hermes-agent/agent/turn_context.py:1111).

El compresor poda resultados antiguos de herramientas, conserva regiones seleccionadas y resume una parte del historial. La persistencia marca los originales compactados como archivados y mantiene su recuperación. También contempla mensajes llegados mientras se genera el resumen. [Compresor](/Users/el-men/Workspace/hermes-agent/agent/context_compressor.py:5526), [archivo no destructivo](/Users/el-men/Workspace/hermes-agent/hermes_state_messages.py:975).

Los procedimientos se presentan mediante un índice de skills y carga de `SKILL.md` o referencias relacionadas. Son instrucciones que el modelo consulta; no entrenamiento de pesos ni validación de las operaciones de negocio. [Carga de skills](/Users/el-men/Workspace/hermes-agent/tools/skills_tool.py:592).

FTS5 busca texto de mensajes y datos de herramientas mediante `MATCH`, fragmentos y ranking BM25. Es recuperación lexical; no convierte automáticamente el archivo histórico en contexto y no genera embeddings. [Búsqueda](/Users/el-men/Workspace/hermes-agent/hermes_state_search.py:1092).

## Qué hace Waku

Waku construye un system prompt con personalidad, hora, reglas, memoria recuperada y skills seleccionadas. Añade por separado una ventana del historial y el mensaje actual; el valor predeterminado de esa ventana es 12 intercambios. Contar intercambios no equivale a limitar tokens, porque sus tamaños varían. [Session](/Users/el-men/Workspace/waku-agent/waku/runtime/session.py:76), [ensamblado](/Users/el-men/Workspace/waku-agent/waku/app.py:207).

Su esquema separa `chat_log`, `facts` y `episodes`. FTS5 indexa hechos y resúmenes de episodios, no directamente el historial bruto de esa ruta. La etiqueta `semantic` del almacén de hechos no demuestra uso de una base vectorial. [Esquema](/Users/el-men/Workspace/waku-agent/waku/db.py:25), [consulta de hechos](/Users/el-men/Workspace/waku-agent/waku/memory/semantic/store.py:100).

La consolidación genera hechos y un episodio a partir de mensajes pendientes, por defecto cada seis intercambios. Marca originales como consolidados, sin borrarlos. La extracción usa un modelo y filtros; no demuestra que los hechos derivados sean correctos. [Consolidación](/Users/el-men/Workspace/waku-agent/waku/memory/consolidation.py:180).

La recuperación puede usar un modelo pequeño para decidir si buscar y generar términos. El resultado se consulta en los almacenes y se incorpora al contexto. No debemos copiar esa llamada adicional por turno sin justificar su necesidad. [Recuperación](/Users/el-men/Workspace/waku-agent/waku/memory/__init__.py:107).

Las skills se cargan desde archivos y se seleccionan lexicalmente. El historial no se transforma por sí solo en nuevos procedimientos aprobados. [Procedimientos](/Users/el-men/Workspace/waku-agent/waku/memory/procedural/loader.py:77).

Dos diferencias que Maia debe conservar frente a esta referencia:

- La ruta de consolidación inspeccionada selecciona mensajes pendientes de todas las sesiones. Maia necesita alcance explícito por conversación, prospecto e intención para no mezclar personas.
- Waku registra el intercambio después de responder en la ruta examinada. Maia ya acordó persistir el mensaje entrante antes de procesarlo, según Q263. [Registro del intercambio](/Users/el-men/Workspace/waku-agent/waku/app.py:155).

## SQLite y FTS5, respuesta concreta

| Responsabilidad | Hermes | Waku, ruta local inspeccionada |
|---|---|---|
| Persistencia | SQLite para sesiones y mensajes; archivos para memoria curada y procedimientos. | SQLite para historial, hechos y episodios; archivos para procedimientos. |
| Búsqueda FTS5 | Mensajes y datos de herramientas del historial. | Hechos y episodios derivados. |
| Selección para el modelo | Constructor de contexto, historial activo y mecanismos de compresión/recuperación. | Ventana reciente, recuperación de hechos/episodios y selección de skills. |

Conservar esas responsabilidades no obliga a adoptar sus motores de almacenamiento. Maia mantiene PostgreSQL como persistencia principal y la decisión de no añadir SQLite ni embeddings en esta versión.

## Contrato propuesto para Maia

Una interfaz pequeña de construcción de contexto puede recibir la conversación, la intención activa cuando exista y los mensajes pendientes. Obtiene exclusivamente datos autorizados para ese alcance y devuelve:

1. Instrucciones y procedimientos aprobados, con versión identificable.
2. Criterios estructurados vigentes de la búsqueda.
3. Estado comercial confirmado que sea pertinente para la ejecución.
4. Mensajes recientes necesarios para continuar.
5. Un resumen previo o fragmentos recuperados, cuando hagan falta y con referencia a su origen.

Las propiedades y horarios actuales se consultan mediante sus módulos cuando la tarea lo requiera. No incluir todo el inventario ni confiar en un precio recordado como disponibilidad actual. Un nuevo mensaje puede corregir preferencias; una declaración de pago no confirma por sí sola el hito comercial.

El código determina alcance y presupuesto de contexto. Haiku interpreta y solicita operaciones; los módulos de negocio las validan. Los resúmenes ayudan a recordar, no autorizan herramientas ni reemplazan las fuentes originales.

Propuesta inicial: cargar determinísticamente el estado mínimo y el historial reciente; generar resúmenes cuando el presupuesto de contexto lo requiera, sin otra llamada al modelo en cada turno para decidir si cargar datos críticos. Falta definir presupuesto, actualización, evidencia de origen y tratamiento de errores. No copiar los umbrales 12/6 de Waku ni el compresor completo de Hermes por similitud.

## Lecciones y límites

- Conservar historial original y derivados por separado.
- Consultar los datos comerciales mediante la interfaz autorizada de cada módulo.
- Identificar el origen y alcance de la información recuperada.
- Mantener procedimientos aprobados separados de las declaraciones de prospectos.
- Poder reconstruir resúmenes a partir del historial.
- Medir necesidad de recuperación y compresión antes de añadir infraestructura o llamadas al modelo.

No se ha evaluado precisión de extracción, recuperación ni compresión en conversaciones inmobiliarias. Los mecanismos observados son referencias de diseño, no una validación de calidad para Maia.

Contratos aprobados que esta propuesta debe respetar: [Q241–Q265](../design/contratos-q241-q265.md).

## Revisión técnica del 7 de noviembre: Maia actual

La configuración exige PostgreSQL; no hay SQLite ni recuperación vectorial implementada en el backend inspeccionado. Esto describe código y configuración, no verifica un servidor vivo. [Configuración](/Users/el-men/Workspace/maia-agent/backend/maia/settings.py:52).

| Información persistente | Modelos actuales | Papel en la memoria |
| --- | --- | --- |
| Inventario | `Property` | Fuente vigente de características, precio y publicación, consultada con filtros SQL. |
| Cliente y relación comercial | `Prospect`, `Advisor`, `ProspectEvent` | Contacto, asesor, criterios, etapa y siguiente paso. No es un almacén libre de recuerdos. |
| Conversación | `Conversation`, `Message` | Historial, acciones de interfaz, fichas históricas, criterios y contacto de esa conversación. |
| Visitas | `Appointment`, `AppointmentProposal`, `AppointmentOperation` | Estado autorizado de propuesta y operación real. Un texto recordado no sustituye estos registros. |
| Seguimiento y transporte | `FollowupCycle`, `FollowupAttempt`, `WhatsAppDelivery`, `WhatsAppEvent`, `Notification` | Programación, permisos y resultados observables de entrega. |
| Diagnóstico | `Execution` | Tokens, tiempo, estado y eventos resumidos de herramientas. No se carga entero como memoria del cliente. |

Fuente: [modelos](/Users/el-men/Workspace/maia-agent/backend/datalayer/models.py:72). Estas son entidades lógicas de una base, no bases independientes.

### Qué entra hoy al modelo

1. Instrucciones de ventas y las dos skills completas, cargadas por `agent/config.py`.
2. Criterios y hechos estructurados de la conversación: contacto, nombre, interés, fichas mostradas, solicitud humana, hora y citas.
3. Historial pertinente completo, sin ventana por cantidad o tokens. Excluye errores y respuestas de WhatsApp todavía no aceptadas, fallidas o inciertas. Las acciones ocultas de interfaz sí informan al agente.
4. Resultados de herramientas ejecutadas durante ese turno. Sus bloques completos viven en el loop; entre turnos se conservan resultados de negocio, mensajes y una traza reducida, no todo el intercambio interno de herramientas.

Esto ya constituye una memoria de trabajo: es contexto ensamblado, no una tabla que deba llamarse `working_memory`. [Carga](/Users/el-men/Workspace/maia-agent/backend/datalayer/agent_state.py:48), [instrucciones](/Users/el-men/Workspace/maia-agent/backend/agent/config.py:6), [loop](/Users/el-men/Workspace/maia-agent/backend/harness/runtime.py:65).

Las fichas históricas se reducen para el contexto a referencias e identificadores; se indica consultar datos actuales. El historial conserva lo mostrado entonces, pero no acredita precio o disponibilidad vigentes. [Proyección histórica](/Users/el-men/Workspace/maia-agent/backend/datalayer/agent_state.py:19).

No se cargan automáticamente todas las conversaciones del mismo teléfono. El website mantiene autorización por navegador y conversación. Existe una continuidad específica hacia WhatsApp desde un seguimiento de la conversación fuente, validada para el mismo prospecto; no es búsqueda global. [Origen autorizado](/Users/el-men/Workspace/maia-agent/backend/datalayer/agent_state.py:63).

### Qué falta, según el rediseño acordado

Durante esta inspección previa, la continuidad era un diseño pendiente. Actualización posterior: se implementó en `Message.continuity`, junto a `Message.presentation`, con propósito, pendiente y referencia de origen. Permanece en PostgreSQL y no reemplaza historial, criterios ni estados comerciales. El [plan técnico](../design/plan-harness-conversacional.md) registra implementación y verificación; la aceptación manual sigue pendiente.

Ejemplo: presupuesto vigente de 25.000 pertenece a criterios; la pregunta «¿Con quién tengo el gusto?» y su pendiente pertenecen a continuidad; una cita confirmada pertenece a las operaciones de citas. Mezclarlos en una nota libre debilitaría validación y procedencia.

## Detalle comparativo de los mecanismos

| Mecanismo | Hermes integrado | Waku local | Maia actual o acordada |
| --- | --- | --- | --- |
| Contexto activo | Historial activo, instrucciones y snapshot de notas; compresión cuando corresponde. | Historial reciente y sistema reconstruido por turno. | Historial pertinente completo, instrucciones, hechos y herramientas. |
| Hechos durables | Notas `MEMORY.md` y `USER.md` cargadas al iniciar. | Filas `facts` recuperadas mediante FTS5. | Campos de conversación y prospecto actualizados mediante herramientas autorizadas. |
| Episodios e historial | SQLite de sesiones y mensajes; originales recuperables tras compresión. | `chat_log` original y `episodes` derivados. | Mensajes originales en PostgreSQL; sin episodios automáticos. |
| Recuperación | `session_search` solicitado por el agente; FTS5 sobre historial. | Gate LLM, términos de búsqueda y FTS5 sobre hechos/episodios. | Consultas por conversación y herramientas de negocio; sin búsqueda general de recuerdos. |
| Procedimientos | Índice de skills y carga bajo demanda. | Selección lexical de skills. | Dos skills obligatorias, completas, en cada contexto del agente. |

### Hermes: no todo recuerdo está en SQLite

Las notas integradas son pequeñas: límites predeterminados de 2.200 caracteres para `MEMORY.md` y 1.375 para `USER.md`. Se inyectan completas mediante un snapshot estable; las escrituras no reescriben inmediatamente el prefijo de la sesión. [Inicialización](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:1329), [snapshot](/Users/el-men/Workspace/hermes-agent/tools/memory_tool_store.py:175).

`session_search` recupera mensajes reales, sesiones o fragmentos alrededor de una coincidencia. La búsqueda integrada no necesita embeddings ni un modelo intermedio. También hay revisión de memoria en segundo plano, cada diez turnos por defecto, separada de la revisión de skills. Son mecanismos de un asistente general; no autorizan autoeditar reglas comerciales de Maia. [Búsqueda](/Users/el-men/Workspace/hermes-agent/tools/session_search_tool.py:655), [revisión](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:1304).

Los proveedores externos de memoria son opcionales y pueden añadir recuperación por turno o vectores. Su presencia en el catálogo no acredita activación ni necesidad para Maia.

### Waku: selección y consolidación tienen coste

Su ventana predeterminada es de 12 intercambios, es decir 24 mensajes previos, más la entrada actual. Recupera hasta cuatro hechos y tres episodios. Un LLM pequeño decide si consultar usando el mensaje actual; si falla, intenta buscar con ese mensaje. [Ventana](/Users/el-men/Workspace/waku-agent/waku/app.py:207), [recuperación](/Users/el-men/Workspace/waku-agent/waku/memory/__init__.py:108), [gate](/Users/el-men/Workspace/waku-agent/waku/memory/retrieval_gate.py:22).

Cada seis intercambios, la consolidación procesa mensajes pendientes y genera hechos y episodios. Es información derivada por un modelo, susceptible de error; conserva los originales. Los Markdown exportados son vistas de SQLite, no su fuente de búsqueda. [Consolidación](/Users/el-men/Workspace/waku-agent/waku/memory/consolidation.py:180), [exportación](/Users/el-men/Workspace/waku-agent/waku/memory/__init__.py:203).

En la ruta local, hechos y episodios pertenecen al mismo `home` y no se filtran por cliente o conversación. Copiar esa recuperación en Maia mezclaría alcances. No se deben reutilizar recuerdos solo porque una búsqueda textual coincide o alguien declara un teléfono. [Esquema local](/Users/el-men/Workspace/waku-agent/waku/db.py:25).

## Recomendación para Maia

Conservar la separación de responsabilidades de ambos ejemplos, dentro de la arquitectura actual:

- PostgreSQL guarda mensajes, hechos estructurados, continuidad y operaciones comerciales.
- El harness construye el contexto autorizado por turno.
- Las skills aprobadas describen comportamiento; los mensajes del cliente son datos y no pueden cambiarlas.
- Las herramientas consultan precios, disponibilidad, permisos y citas vigentes antes de actuar.
- Una búsqueda histórica futura recuperaría evidencia del cliente autorizado, sin sustituir fuentes de negocio ni mezclar sesiones por similitud.

SQLite sería otro motor que operar y sincronizar sin una necesidad demostrada. FTS5 es búsqueda textual de SQLite, no sinónimo de memoria ni embeddings. Si aparece una necesidad real de recuperación textual, evaluar primero la base existente. Este análisis no selecciona ni implementa un índice de búsqueda de PostgreSQL.

No introducir ahora consolidación automática, compresión, vectores, notas libres por cliente ni otra llamada LLM de recuperación por turno. Siguen vigentes los acuerdos de historial completo pertinente y simplicidad. La continuidad nueva resuelve el pendiente del diálogo; los mecanismos históricos resuelven otro problema y deben justificarse con casos de uso y fallos observados.

Límite de verificación: revisión estática de código y configuración. Sin ejecución de agentes, consultas a datos de clientes, pruebas de recuperación ni mediciones de calidad o rendimiento.
