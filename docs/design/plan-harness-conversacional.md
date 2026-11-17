# Plan técnico del harness conversacional

Fecha: 7 de noviembre de 2026.

Estado: implementación autorizada por Guillermo y realizada. Contrato, continuidad, loop, instrucciones y presentación por canal integrados. Pruebas técnicas aprobadas; aceptación manual del comportamiento y dispositivos pendiente. Seguimos en pre-BETA y en el mismo incremento.

Visualización: [mapas de arquitectura actual, rediseño y memoria](../architecture/harness/index.html), con [guía de alcance](../architecture/harness/README.md). Los bloques muestran responsabilidades lógicas, no nuevos servicios.

## Resultado esperado

Una respuesta reúne texto, fichas, controles y continuidad. El LLM propone cómo seguir; el software autoriza acciones, comprueba referencias y publica la respuesta completa. Ninguna capa añade después otra pregunta o un control ajeno al propósito del turno.

Reutilizar el agente, el loop, PostgreSQL y la cola existentes. No añadir otro agente, almacén de memoria ni juez LLM en vivo.

## Problemas encontrados antes de la implementación

| Lugar | Comportamiento actual | Cambio necesario |
| --- | --- | --- |
| `backend/harness/runtime.py` | El clic de interés adelanta horarios y activa la petición de nombre. | Tratar el clic como contexto para elegir la continuación. |
| `backend/datalayer/agent_state.py` | Añade la pregunta del nombre después de redactar. | Validar y guardar la respuesta completa, sin apéndices. |
| Instrucciones y skills de `backend/agent` | Mezclan nombre automático, petición temprana de celular y una excepción a la petición principal. | Alinear voz, política y procedimientos con el comportamiento acordado. |
| `Chat.tsx` y `backend/datalayer/presentation.py` | Reordenan preguntas mediante expresiones regulares. | Renderizar una presentación explícita y ordenada. |
| `ContactCard.tsx`, `VisitCard.tsx` y `backend/datalayer/whatsapp.py` | Ofrecen controles por estado global, aunque la respuesta atienda otra necesidad. | Mostrar el control pertinente a esa respuesta. |

Las rutas frontend anteriores pertenecen a `frontend/src/main-website/components`.

## Contrato mínimo propuesto

La salida final contiene texto, referencias ordenadas a fichas o controles y continuidad siguiente. Los datos públicos de propiedades y los controles se construyen desde fuentes verificadas. El modelo no proporciona permisos ni inventa identificadores.

La continuidad contiene propósito actual, pendiente si existe y referencia de origen. Los hechos comerciales siguen en sus modelos actuales. Un nombre desconocido no se convierte en rechazo ni obliga a preguntarlo otra vez.

Q15 acordada e implementada: guardar presentación y continuidad junto a la respuesta, dentro de PostgreSQL. Los campos JSON opcionales de `Message` conservan compatibilidad; la continuidad identifica la versión del contrato y su origen. Se elige desde la última respuesta elegible del canal, sin duplicarla en `Conversation`. Los mensajes antiguos no se reescriben.

Q14 acordada con Guillermo: usar una herramienta terminal sin efectos comerciales para proponer la respuesta completa. El harness valida y publica la propuesta. Q16 acordada: permitir una corrección de la propuesta final dentro del tiempo disponible, sin repetir operaciones comerciales; después, recuperación basada en hechos comprobados. No depender de capacidades del proveedor sin verificarlas.

### Comparación de salida final y elección acordada

El runtime actual consume bloques `tool_use` y termina cuando recibe texto sin herramientas. El SDK está fijado en `anthropic==0.125.0` en `backend/uv.lock`. La integración existente favorece reutilizar bloques de herramientas; esto no demuestra que una opción produzca conversaciones más naturales.

| Opción | Ventaja | Coste o límite |
| --- | --- | --- |
| JSON solicitado mediante instrucciones | Aprovecha el bloque de texto actual. | Puede llegar JSON inválido, prosa adicional o campos incorrectos; exige análisis y reparación locales. |
| JSON nativo con esquema del proveedor | Ofrece una salida final explícita y restringida por esquema. | Requiere verificar compatibilidad del modelo y del SDK desplegados, manejar truncamiento y negativas y adaptar el cliente. No exige por definición otra llamada. |
| Herramienta terminal, por ejemplo `propose_reply` | Reutiliza el protocolo de herramientas actual para presentar texto, referencias y continuidad juntos. | Exige distinguir cierre de operaciones, validar localmente y manejar una llamada omitida, inválida o mezclada con otras herramientas. El uso ordinario de herramientas no garantiza cumplimiento estricto del esquema. |

Elección acordada: herramienta terminal sin efectos comerciales, manejada por el harness. Su nombre expresa que propone una respuesta; no envía mensajes ni confirma reservas. Una propuesta válida cierra el loop sin pedir al modelo que vuelva a redactarla. El harness comprueba y publica mediante las operaciones existentes. No requiere automáticamente una llamada adicional, aunque los errores de formato pueden requerir corrección.

Condiciones propuestas:

- Rechazar una generación truncada antes de ejecutar cualquier llamada contenida en esa generación.
- Exigir una única propuesta terminal, sin operaciones comerciales en el mismo bloque de respuesta. Si se mezclan, no ejecutar ese lote; devolver el error de protocolo y continuar dentro del presupuesto.
- Construir fichas y controles desde referencias autorizadas y resultados reales. Nunca interpretar el texto como autorización para reservar.
- Ante una propuesta final inválida, permitir una corrección limitada a la propuesta, sin habilitar nuevas escrituras comerciales ni repetir resultados anteriores.
- Conservar presupuesto y salida de recuperación si el modelo no produce una propuesta válida. No contar la propuesta como publicada antes de su aceptación por el harness y el estado correspondiente del canal.

La auditoría del protocolo añade dos requisitos de implementación: resolver cada llamada rechazada con su resultado de error antes de continuar el historial del proveedor, o excluir la respuesta inválida del contexto de reparación; y actualizar los mocks que hoy declaran `end_turn` aun cuando contienen `tool_use`. La restricción de herramientas durante la corrección también se comprueba en código, sin confiar únicamente en el parámetro enviado al proveedor.

La elección del transporte no impone un guion comercial. La continuación sigue siendo contextual; el esquema ordena cómo comunicar y comprobar esa decisión.

Fuentes: [contrato de herramientas de Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works) y [salidas estructuradas](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). La documentación distingue JSON nativo, herramientas ordinarias y herramientas estrictas. No se probó una llamada real del nuevo contrato ni se seleccionó `strict: true` por este análisis.

## Construcción del contexto: contrato acordado

Q17 acordada e implementada: separar instrucciones, entrada, hechos, continuidad, historial y resultados de herramientas. La continuidad orienta, las preferencias admiten corrección y los hechos comerciales conservan sus validaciones. `harness/memory/context.py` construye el contexto; `datalayer/replies.py` aplica la aceptación con hechos actuales y `datalayer/turns.py` persiste el turno. La política pura reside en `harness/replies/validation.py`.

Construir el contexto mediante código determinístico a partir del alcance autorizado de la conversación. No añadir un LLM para decidir si se cargan datos esenciales. Se mantiene el historial completo pertinente acordado; este contrato no introduce resumen, ventana ni compresión.

| Bloque | Contenido y autoridad |
| --- | --- |
| Instrucciones aprobadas | Identidad, límites comerciales, procedimientos y skills. Son instrucciones; los mensajes y resultados externos son datos. |
| Entrada y alcance | Mensajes o acciones pendientes, conversación, canal y revisión. Cada entrada aparece una vez en el historial; su referencia identifica qué se está atendiendo. |
| Hechos estructurados | Criterios, selección, contacto y estados pertinentes de la conversación. Distinguir declarado, confirmado, desconocido y no aplicable cuando el dominio lo requiera. No considerar declarado como confirmado. |
| Continuidad previa | Propósito y pendiente vinculados a la última respuesta elegible. Orientan la interpretación; no obligan a mantener el propósito frente a una petición nueva. |
| Historial pertinente | Mensajes y acciones autorizadas, conservando orden y filtros de publicación. Las fichas históricas describen lo presentado entonces, no la vigencia actual del inventario. |
| Herramientas disponibles | Operaciones autorizadas y sus contratos. Su disponibilidad no obliga a ejecutarlas ni a mostrar todos sus controles. |
| Resultados del turno | Consultas y operaciones realmente ejecutadas, con referencias y errores. Sus resultados delimitan la propuesta final. |

Cada hecho necesita una fuente identificable según el dominio: mensaje, registro comercial o resultado de herramienta. No se propone envolver todos los campos en un esquema genérico de memoria ni copiar el inventario completo al contexto.

### Correcciones e incertidumbre

- Si el cliente cambia de 25.000 a 30.000 de presupuesto, el mensaje nuevo expresa una corrección. El agente usa la herramienta existente para actualizar criterios; el criterio anterior no funciona como instrucción para ignorar el cambio.
- Si dice «ya pagué», esa declaración no modifica un hito que requiere confirmación humana.
- Si antes preguntamos nombre y ahora pregunta mascotas, la continuidad previa explica la interrupción; no exige volver al nombre ni demuestra una negativa.
- Si una característica se desconoce, mantenerla desconocida. La falta de información no equivale a una respuesta negativa.
- Consultar precio, publicación y disponibilidad mediante herramientas vigentes cuando la respuesta o acción lo requiera. Una copia histórica no acredita su estado actual.

La precedencia depende del dato: una preferencia puede corregirse mediante declaración; un pago o reserva necesita su operación autorizada. No aplicar una regla universal de «gana el último texto».

### Alcance y salida

No recuperar historial de otros clientes ni todas las conversaciones de un teléfono por coincidencia textual. Conservar los mecanismos existentes de autorización y continuidad explícita entre canales. Los datos privados del CRM no pasan al contexto público del agente por compartir base de datos.

El constructor devuelve una instantánea para la revisión atendida y referencias suficientes para validar la propuesta. Las transacciones de lectura y escritura son cortas; no se mantiene una transacción abierta mientras responde el LLM o un servicio externo. Antes de publicar se vuelve a comprobar revisión y pausa; las operaciones comerciales mantienen sus validaciones de vigencia.

Referencia comparativa: [Hermes, Waku y memoria de Maia](../research/contexto-memoria-hermes-waku-2026-10-24.md). El almacenamiento de continuidad, la herramienta final y este contrato de contexto están implementados; la aceptación conversacional sigue pendiente.

## Publicación y resultados comerciales

| Canal o resultado | Tratamiento propuesto |
| --- | --- |
| Website | Guardar mensaje y continuidad juntos; publicarlos mediante el contrato HTTP. Eso no demuestra que el navegador los mostró ni que el cliente los leyó. |
| WhatsApp en cola o enviándose | Conservar la propuesta; no acreditar todavía una pregunta presentada. |
| WhatsApp aceptado por Meta | Vincular continuidad al mensaje aceptado. No confundir aceptación con entrega o lectura. |
| Confirmación de entrega o lectura | Registrar el estado observado sin exigir lectura para seguir conversando. |
| Envío fallido, bloqueado, omitido o incierto | Conservar diagnóstico y evitar reenvío ciego o avance ficticio del diálogo. |
| Reserva ejecutada y respuesta fallida | Conservar la reserva y recuperar su resultado, sin ejecutarla otra vez. |

Reutilizar `WhatsAppDelivery`, revisiones e idempotencia. Un callback tardío no debe sustituir la continuidad de una respuesta posterior.

## Orden de trabajo

1. **Contrato y persistencia.** Definir esquema y validadores en `datalayer/schemas.py`; añadir snapshots compatibles en `models.py`; cargar y guardar continuidad en `agent_state.py`. Crear únicamente la migración necesaria, conservando el identificador Django `core`.
2. **Loop e instrucciones.** Adaptar `agent/tools.py`, `agent/config.py`, instrucciones, skills y `harness/runtime.py`. Retirar nombre añadido y consulta obligatoria de horarios. Mantener herramientas, límites, revisiones y pausas.
3. **Presentación por canal.** Proyectar la salida en `datalayer/conversations.py`; adaptar `Chat.tsx`, `ContactCard.tsx`, `VisitCard.tsx`, `datalayer/presentation.py` y `datalayer/whatsapp.py`. Conservar endpoints y confirmaciones existentes; actualizar tipos del contrato HTTP cuando corresponda.
4. **Recuperación y diagnóstico.** Proponer una corrección de salida usando resultados existentes, sin repetir escrituras comerciales. Si falla, responder con hechos comprobados. Registrar pendiente anterior, continuación, referencias y validación en `llm_ops/executions.py`, sin razonamiento interno del modelo.
5. **Evaluación.** Sustituir pruebas que exigen la pregunta añadida y horarios automáticos; ejecutar recorridos completos y regresiones. Después validar manualmente website y WhatsApp.

Cada bloque debe dejar un recorrido verificable. No cambiar estados comerciales del CRM para representar pasos internos del LLM.

## Verificación necesaria

- D01–D10 del documento de comportamiento: explorar, interés genérico, fecha concreta, interrupciones, datos conjuntos, condiciones desconocidas, contacto por canal, solicitudes compatibles y cierre. Todos aceptados por Guillermo como criterios. Existen pruebas de contrato y regresión; su aceptación manual con el modelo real sigue pendiente. Comprobar resultados y secuencias, sin imponer frases literales.
- Recarga y reinicio conservan propósito y pendiente sin repetir preguntas conocidas.
- Doble clic, revisión obsoleta y pausa humana conservan aislamiento e idempotencia.
- Una corrección no repite escrituras; una reserva ejecutada sobrevive a un fallo de redacción o envío.
- Envíos inciertos y callbacks fuera de orden no inventan entrega ni sobrescriben continuidad posterior.
- Website y WhatsApp muestran controles pertinentes; no repiten fichas ni publican mensajes escritos ficticios del cliente.
- Pruebas existentes, compilación frontend, contrato HTTP y proxy real con la plataforma arrancada. Revisar las migraciones generadas frente al único cambio de persistencia previsto.
- Revisión manual en desktop, iPad y móvil; naturalidad evaluada sobre conversaciones completas, con criterio comercial de Santiago cuando participe.

El esquema comprueba estructura, referencias y condiciones. No demuestra por sí solo naturalidad ni veracidad de todo texto libre. Las pruebas determinísticas y la evaluación conversacional cubren responsabilidades distintas.

## Resultado de implementación

- Ruff y comprobación Django aprobados; no hay migraciones adicionales por generar tras `0007_message_reply_contract`.
- 183 pruebas aprobadas y dos opcionales omitidas en la suite normal. Incluye los contratos nuevos y las regresiones existentes.
- Una prueba opcional separada con Haiku real aprobada: interés, interrupción por mascotas y nombre aportado. Usa base de pruebas, sin envíos WhatsApp; simula aceptación del proveedor localmente y conserva la baja y ausencia de permiso.
- TypeScript y compilación de producción aprobados. Backend, worker y website actualizados; migración aplicada sin reescribir mensajes anteriores.
- Proxy real comprobado: creación y lectura de conversación por el website con HTTP 200. La conversación anterior cargó en navegador sin reescribirla.

Estos resultados no aprueban automáticamente la naturalidad de D01–D10 ni la presentación en dispositivos físicos. Las pruebas programadas comprueban secuencias; el modelo puede elegir otra continuación. Véase la [validación manual](../testing/harness-conversacional.md).


## Reorganización por responsabilidades, 7 de noviembre de 2026

Guillermo autorizó aplicar los cuatro candidatos de la revisión: memoria funcional, aceptación y presentación, herramientas y ciclo del chat. El [mapa actual de código](../architecture/harness/code-map.md) reemplaza las rutas históricas para localizar la implementación. `agent_state.py` se dividió entre lectura de memoria, transacciones del turno y acciones comerciales; no queda un módulo de reexportación.

Se conservan instrucciones, contrato HTTP, autorización por sesión/canal, esquema de datos, cola y límites del loop. La segunda validación dentro de la transacción de publicación permanece. La verificación de esta reorganización se registra en [pruebas del harness](../testing/harness-conversacional.md).
