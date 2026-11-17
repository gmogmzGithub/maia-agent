# Comportamiento conversacional y loop de Maia

Fecha: 7 de noviembre de 2026.

Estado: comportamiento, responsabilidades, recuperación, evaluación, continuidad, herramienta final y contrato de contexto acordados con Guillermo. D01–D10 aceptados como criterios de comportamiento. Implementación autorizada y realizada; pruebas técnicas aprobadas según el plan. Aceptación manual de naturalidad y dispositivos pendiente.

## Propósito

Maia atiende la intención actual del cliente, conserva el contexto y facilita el siguiente paso. Puede alternar entre explorar, resolver dudas y coordinar una visita sin obligar a seguir un formulario.

## Acuerdos

| Tema | Comportamiento acordado |
| --- | --- |
| Turnos | Una petición principal por respuesta. Aceptar varios datos y solicitudes compatibles en un mensaje. |
| Nombre | Pedirlo cuando encaje, normalmente después del interés genérico. Es opcional; no interrumpe una petición concreta ni bloquea una visita. |
| Nombre desplazado | Si responde con otra duda, atenderla y continuar sin repetir automáticamente el nombre. Dato desconocido no equivale a negativa. |
| Celular | Ofrecer horarios antes de pedirlo. Tras elegir uno, solicitarlo si falta para completar la reserva. Aprovechar el contacto ya registrado en el canal. |
| Condiciones | Resolver primero una condición que afecte la visita, como aceptación de mascotas. Si se desconoce, ofrecer revisión humana. Visitar sigue siendo posible si el cliente lo prefiere, sin declarar resuelta la condición. |
| Iniciativa | El LLM interpreta y propone la continuación según el contexto; el harness controla datos, permisos, condiciones y ejecución. |
| Composición | Preparar juntos texto, fichas, controles y pregunta pendiente. Evaluar la respuesta completa, sin añadir preguntas automáticamente después. |
| Arquitectura | Un agente con herramientas y un harness que controla el turno. Los pasos lógicos no requieren agentes o llamadas independientes. |
| Recuperación | Rechazar propuestas incompatibles y permitir una corrección dentro del mismo agente, conservando resultados y sin repetir acciones comerciales. Si falla, comunicar el problema brevemente sin inventar éxito. |
| Evaluación | Comprobaciones técnicas durante la atención; naturalidad evaluada fuera de la atención en vivo, sobre conversaciones completas. No añadir un segundo LLM a cada intercambio. |
| Continuidad | Conservar el historial y persistir un estado pequeño: propósito actual, pregunta o decisión pendiente si existe y mensaje o acción de origen. Actualizarlo consistentemente con la conversación. |
| Publicación | Vincular la continuidad a la respuesta publicada según el estado observable del canal. Un borrador descartado no cuenta como pregunta realizada. Un fallo de redacción o envío no revierte una operación comercial ejecutada. Publicación no acredita lectura. |
| Cierre técnico | Usar una herramienta final sin efectos comerciales para proponer texto, presentación y continuidad juntos. El harness valida y publica; no solicita otra redacción después de una propuesta válida. |
| Persistencia del turno | Guardar presentación y continuidad junto al mensaje en PostgreSQL, con estructura validada y compatible con mensajes antiguos. |
| Presupuesto de corrección | Permitir una corrección de la propuesta final dentro del tiempo disponible, sin repetir operaciones comerciales. Si falla, recuperar con hechos comprobados. |
| Autoridad del contexto | Separar instrucciones, entrada, hechos, continuidad, historial y resultados. La continuidad orienta; una preferencia puede corregirse mediante herramientas; un hito comercial requiere su validación autorizada. |

Se conservan las restricciones de negociación, autorizaciones, aislamiento, confirmación de contacto, reservas y control humano ya documentadas. El interés no concede permisos ni confirma una cita.

## Comportamientos disponibles

| Comportamiento | Cuándo ayuda | Resultado esperado |
| --- | --- | --- |
| Explorar | Necesita encontrar o ajustar opciones. | Usar requisitos suficientes o pedir la siguiente aclaración útil. |
| Resolver dudas | Pregunta por características, condiciones o proceso. | Contestar con hechos vigentes o identificar lo desconocido. |
| Atender interés | Selecciona una propiedad. | Continuar desde esa selección, sin repetir ficha ni inventar un mensaje escrito. |
| Conocer al cliente | Un dato aporta al siguiente paso. | Pedir solo lo que falta, con propósito comprensible. |
| Coordinar visitas | Solicita o acepta avanzar hacia una visita. | Disponibilidad real, datos necesarios y confirmación correspondiente. |
| Gestionar cambios | Quiere reprogramar o cancelar. | Respetar su intención y comunicar el resultado comprobado. |
| Pedir apoyo humano | Lo solicita o una condición necesita al asesor. | Conservar contexto y pendientes sin inventar compromisos ni entregas. |

La selección es contextual. Una pregunta sobre mascotas puede suspender el agendamiento; una respuesta con varios datos puede adelantar pasos sin nuevas preguntas.

## Recorrido conceptual de un turno

1. **Interpretar la entrada.** Diferenciar selección, pregunta, datos, corrección y cierre. Una entrada puede contener varias aportaciones.
2. **Actualizar el contexto.** Incorporar datos explícitos y determinar qué ocurrió con el pendiente anterior. Un clic de interés no responde al nombre.
3. **Elegir la continuación.** Proponer el comportamiento pertinente y qué respuesta se necesita del cliente, si hace falta alguna.
4. **Ejecutar herramientas.** Validar autorización y condiciones antes de consultar o modificar datos. Los resultados verificados delimitan lo que puede afirmarse.
5. **Componer la respuesta.** Redactar texto y presentar controles coherentes con el siguiente paso. Evitar fichas y preguntas redundantes.
6. **Validar y guardar.** Comprobar el contrato, referencias y resultados; descartar respuestas obsoletas. Conservar el contexto necesario para el siguiente turno.

Las herramientas pueden requerir varias rondas dentro del loop existente. La división anterior define responsabilidades, no una llamada adicional por paso.

## Información que necesitamos distinguir

Estos conceptos no deciden todavía nombres de campos, tablas o estados del CRM.

| Concepto | Ejemplo |
| --- | --- |
| Hechos conocidos y procedencia | Nombre expresado; celular confirmado o aportado por WhatsApp; propiedad consultada. |
| Necesidad actual | Confirmar mascotas antes de decidir una visita. |
| Pendiente conversacional | Se preguntó el nombre, pero el cliente planteó otra duda. |
| Condición comercial pendiente | Falta confirmar el celular o ejecutar la reserva. |
| Resultado de una acción | Hay horarios consultados; todavía no existe una cita. |
| Motivo operativo de la continuación | Atender primero una condición expresada por el cliente. |

Un dato faltante, una pregunta enviada y una respuesta esperada tienen significados distintos. El historial puede conservarlos, pero un único booleano de nombre preguntado no los representa por completo.

## Memoria mínima de continuidad acordada

El historial conserva lo ocurrido. El estado de continuidad expresa qué intenta resolver Maia ahora y qué respuesta espera, si necesita alguna. Incluye el propósito actual, el pendiente y su referencia de origen. Puede cambiar cuando el cliente plantea otra intención; no impone etapas obligatorias.

Ejemplo: Maia preguntó el nombre, pero el cliente pidió confirmar mascotas. Conservamos que el nombre falta sin interpretar una negativa. La necesidad actual pasa a resolver mascotas y la pregunta del nombre no se repite automáticamente.

El estado sobrevive a recargas y reinicios mediante `Message.continuity`, junto a `Message.presentation` en PostgreSQL. El esquema está definido en `ReplyProposal`, `DialogueContinuity` y `DialoguePending`. Su ventaja es evitar reconstruir por inferencia todo el propósito del diálogo; su coste es mantenerlo consistente con mensajes y resultados. No se introduce otro almacén ni otra base de datos.

## Contrato del turno acordado

Este contrato expresa qué debe conocer cada parte y qué puede devolver. No selecciona todavía formato, mecanismo del proveedor ni esquema de persistencia.

| Parte | Información o responsabilidad |
| --- | --- |
| Entrada | Aportación actual, identificada como texto o acción, con referencia a su conversación y revisión. |
| Contexto | Historial pertinente, continuidad, datos conocidos y procedencia, propiedades seleccionadas, resultados de herramientas y condiciones del canal. |
| Propuesta del LLM | Continuación pertinente, respuesta completa, referencias a fichas o controles necesarios y siguiente interacción esperada, si existe. |
| Control del software | Autorizar herramientas, verificar argumentos y resultados, construir datos y controles desde sus fuentes, comprobar referencias y vigencia de la revisión. |
| Salida aceptada | Texto y presentación coherentes con el siguiente paso, vinculados con la continuidad que utilizará el próximo turno. |

El LLM puede solicitar herramientas durante el loop. La respuesta final se compone con sus resultados reales. Proponer una continuación no concede permisos, modifica el CRM ni ejecuta una reserva.

### Ejemplo: varios datos en una respuesta

Entrada: «Soy Ana, el lunes a las 11 me funciona y mi WhatsApp es…». El horario corresponde a una opción previamente ofrecida y debe revalidarse según las condiciones de reserva.

- Usar la herramienta correspondiente para guardar el nombre expresado.
- Conservar la preferencia de horario.
- En website, preparar el celular declarado para la confirmación existente, sin tratarlo como confirmado.
- Proponer una respuesta cuyo siguiente paso sea confirmar el número; presentar ese control sin añadir otra pregunta del nombre o de horario.
- Después de esa interacción, continuar con la confirmación de visita cuando se cumplan sus condiciones.

Una petición principal puede coexistir con la incorporación de varios datos. La disponibilidad de un formulario o de un dato faltante no obliga a mostrar otra invitación en ese turno.

### Consistencia que falta concretar

La representación del estado y sus actualizaciones debe distinguir borrador, respuesta presentada y ejecución comercial. Una propuesta descartada no acredita que el cliente haya recibido una pregunta. Los resultados reales de herramientas conservan su estado aunque falle la redacción.

Se acordaron la herramienta final, la persistencia junto al mensaje y una corrección dentro del tiempo disponible. Quedan por concretar el esquema, los estados de publicación por canal y la actualización consistente de mensaje y continuidad en el [plan técnico](plan-harness-conversacional.md).

## Instrucciones y control

- **Identidad y voz:** cómo se presenta y se expresa Maia.
- **Política comercial:** límites, autorizaciones y condiciones para actuar.
- **Procedimientos:** cómo usar herramientas y gestionar resultados o fallos.
- **Contexto del turno:** hechos, necesidades y pendientes de esta conversación.

Esta separación es conceptual. No obliga a crear `SOUL.md` ni a mover archivos. La organización actual y el comportamiento implementado siguen descritos en [code-structure.md](../architecture/code-structure.md).

La validación determinística puede comprobar contratos, referencias, permisos y condiciones estructuradas. La pertinencia y naturalidad también requieren evaluar diálogos; no quedan demostradas por una respuesta sintácticamente válida.

## Recuperación y evaluación acordadas

Antes de ejecutar herramientas se comprueban argumentos, autorizaciones y condiciones. Antes de publicar se comprueba que la propuesta sea coherente con los resultados y controles disponibles. Una incompatibilidad detectada provoca una corrección dentro del agente actual, usando los resultados reales sin repetir acciones comerciales.

Si la corrección falla, el mensaje debe conservar lo comprobado y explicar brevemente qué falta. Un fallo de redacción no demuestra que una reserva haya fallado: cualquier resultado ya ejecutado conserva su estado real. Ante una respuesta obsoleta se descarta esa respuesta; no se fuerza su corrección sobre datos superados.

Durante la atención se comprueban datos estructurados, permisos, referencias y consistencia con las acciones. Fuera de ella se revisan conversaciones de prueba y muestras del piloto; Santiago puede aportar criterio comercial. Una evaluación con otro modelo puede ayudar fuera de la atención, sin sustituir hechos ni aceptación humana.

La propuesta usa una herramienta final y admite una corrección dentro del tiempo disponible. El esquema y la recuperación están implementados; sus textos y comportamiento siguen sujetos a aceptación manual. La comprobación técnica no garantiza detectar todas las contradicciones semánticas de texto libre.

## Diálogos de referencia para revisar

Son simulaciones, no ejecuciones ni textos obligatorios. En la aplicación, horarios y características deben proceder de las herramientas.

Guillermo aceptó D01–D05 mediante ejemplos de diseño y D06–D10 mediante la revisión Q18 de sus recorridos y criterios. La aceptación incluye pedir el celular después de elegir horario, conservar las confirmaciones del website y evaluar resultados y secuencias sin exigir frases literales. Describe el comportamiento esperado; no acredita implementación, pruebas ni aceptación de Santiago o clientes reales.

| Caso | Intercambio | Criterio de aceptación |
| --- | --- | --- |
| D01: exploración | Cliente: «Un departamento hasta $25,000 al mes». Maia muestra coincidencias y ofrece seleccionar mediante la ficha. | La selección es el siguiente paso claro; no añade nombre y celular. |
| D02: interés genérico | Clic «Me interesa». Maia: «Claro, te ayudo a coordinar una visita. ¿Con quién tengo el gusto?». Cliente: «Ana». Maia ofrece horarios verificados. | Da espacio para responder al nombre; no repite la ficha. La presentación del nombre no es obligatoria. |
| D03: solicitud concreta | Cliente: «Me interesa. ¿Puedo verla mañana?». Maia consulta y ofrece opciones reales para esa fecha. | Atiende la petición antes de pedir un dato opcional. |
| D04: interrupción | Maia pregunta nombre. Cliente: «Antes, ¿aceptan perros?». Maia responde con el dato o reconoce que falta. | Conserva la selección y atiende la condición. No insiste con el nombre. |
| D05: información conjunta | Cliente da nombre, horario y celular. Maia aprovecha los tres datos. En website, prepara el número para la confirmación existente antes de reservar. | No pregunta lo ya expresado ni confunde celular declarado con confirmado. |
| D06: condición desconocida | Necesita que acepten dos perros; no hay confirmación. Maia ofrece revisión del asesor. Si el cliente prefiere visitar mientras tanto, continúa con horarios. | No inventa aceptación ni impone una visita como solución a la incertidumbre. |
| D07: visita desde website | Cliente elige horario y falta contacto. Maia solicita el celular; después continúa con las confirmaciones necesarias. | Una necesidad clara por intercambio; ningún anuncio de reserva antes del resultado. |
| D08: visita desde WhatsApp | Cliente elige horario y el canal ya identifica el número. | Reutiliza contacto y pide únicamente lo que falte. |
| D09: solicitudes compatibles | Pregunta precio, mascotas y disponibilidad para mañana. | Atiende las solicitudes posibles; deja una decisión principal pendiente. |
| D10: rechazo o cierre | Cliente rechaza dar nombre o se despide. | Respeta la decisión. Sigue atendiendo si lo pide; ante despedida, cierra sin otra pregunta comercial. |

## Verificación y siguientes decisiones

1. Acordar el inicio de implementación sobre el plan técnico y los criterios D01–D10.
2. Implementar los esquemas, persistencia y validación del turno, conservando los permisos y operaciones existentes.
3. Integrar loop, instrucciones y presentación por canal, con recuperación y diagnóstico.
4. Ejecutar pruebas integradas de recorridos, concurrencia, entrega e idempotencia y las regresiones existentes.
5. Validar conversaciones reales y presentación en desktop, iPad, móvil y WhatsApp. Santiago puede aportar criterio comercial; su revisión no se ha realizado.

Registrar intención atendida, datos reutilizados, pendiente anterior, continuación elegida y resultados reales. Un motivo operativo breve basta para explicar una decisión; no hace falta guardar razonamiento interno del modelo.

Guillermo autorizó iniciar la implementación después de revisar los mapas. El [plan técnico](plan-harness-conversacional.md) registra los cambios y las comprobaciones realizadas. La aceptación de ejemplos de diseño no sustituye la evaluación manual del comportamiento del modelo ni las pruebas en dispositivos.

## Referencias

- [Plan técnico del rediseño](plan-harness-conversacional.md): cambios propuestos sobre el código actual, orden y verificación.
- [Investigación de política de turnos](../research/politica-turnos-conversacion-2026-11-07.md): fuentes, alternativas y límites de la evidencia.
- [Investigación de comunicación humana](../research/comunicacion-humana-2026-11-07.md): tono y muestras aisladas anteriores.
- [Matriz de regresiones](../testing/mejoras-transversales.md): pruebas existentes; no declara implementado este rediseño.
