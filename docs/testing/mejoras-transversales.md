# Mejoras recientes: regresiones por fase

Registro: 7 de noviembre de 2026. Seguimos validando el cuarto incremento. Esta lista no cierra el incremento ni declara un cambio de fase.

Los incrementos agrupan funciones; Pre-Alpha, Alpha, Beta, RC y GA indican madurez. Aplican los [criterios de fases acordados](../design/acuerdos-q215-q240.md#5-criterios-de-fases).

## Documentación de los acuerdos

- [Arquitectura](../architecture/code-structure.md): responsabilidades, skills obligatorias, presentación por canal, nombre, avisos y publicación.
- [Diseño del cuarto incremento](../design/cuarto-incremento-seguimiento.md#mejoras-transversales): comportamiento aceptado y límites.
- [Validación del cuarto incremento](cuarto-incremento.md): evidencia, pendientes y comandos.
- [WhatsApp del piloto](whatsapp-setup.md): configuración y textos presentados a Meta.

No se crea un ADR por cada ajuste de texto, filtro o animación. Son cambios reversibles de producto; sus acuerdos y pruebas quedan en los documentos anteriores.

Actualización: M21 sustituye la secuencia automática del nombre y los horarios descrita históricamente en M06/M19 y la corrección de M02. Conserva sus criterios de datos, aislamiento y presentación. Los registros anteriores no acreditan aceptación manual del harness nuevo.

## Casos para Alpha

Ejecutar con Guillermo y Santiago sobre datos PRUEBA. Una prueba automática no equivale a aceptación manual.

| ID | Recorrido | Resultado esperado | Evidencia y pendiente |
| --- | --- | --- | --- |
| M01 | Buscar en website y WhatsApp; cambiar requisitos y pedir más opciones. | Hasta tres fichas con precio, zona y hasta tres características pertinentes. Introducción breve, sin repetir fichas ni IDs internos. Pregunta después de las fichas. Conservar advertencias de prueba y datos desconocidos. | Presentación aprobada por Guillermo. Repetir al cambiar mensajes. |
| M02 | Forzar texto de inventario que repita fichas en una prueba controlada. | Una corrección sin herramientas; si falla, introducción fija. Logs identifican corrección o fallback. No repetir acciones comerciales. | Cubierto automáticamente y comprobado con Haiku real. |
| M03 | Crear, reprogramar y cancelar visitas en ambos canales; repetir el botón. | Ofrecer horarios disponibles y mostrar propuesta con botón antes de ejecutar. Confirmar solo el resultado verificado, con tono humano. No duplicar acciones. | Flujo WhatsApp validado por Guillermo tras corregir el botón. Repetir ambos canales y la deduplicación como regresión. |
| M04 | Revisar Telegram tras cada evento de cita, incluso sin interés registrado; reintentar un aviso rechazado de prueba. | Evento, propiedad y horario legible correctos, sin campos vacíos. Reintentar conserva los datos del evento. No reenviar avisos entregados o inciertos. | Tono aprobado; instantánea y reintento cubiertos automáticamente. |
| M05 | Pedir atención humana; pausar en CRM, escribir, reanudar y escribir otra vez. | Aviso de atención con resumen, contacto disponible y enlace al CRM. Durante la pausa, guardar sin responder. Reanudar no envía respuestas atrasadas. | Aprobado por confirmación manual de Guillermo para website y WhatsApp el 7 de noviembre: aviso, pausa y reactivación. El aviso reciente observado en registros corresponde al website; la validación WhatsApp se sustenta en su confirmación. Baja WhatsApp comprobada vigente, sin ciclos abiertos. |
| M06 | Consultar una propiedad sin nombre conocido; dar el nombre, ignorarlo o rechazar la pregunta en sesiones separadas. | Responder primero y preguntar el nombre una sola vez, sin bloquear ni insistir. Guardar el nombre expresado y no volver a pedirlo. No inferirlo del asesor ni de la propiedad. | Pruebas automáticas y Haiku real aprobados; aceptación manual pendiente. |
| M07 | Declarar desde otra sesión web el mismo celular de una ficha existente y dar otro nombre. | Conservar el nombre de esa sesión sin sobrescribir la ficha compartida ni revelar otra conversación. Registrar nombre no inicia ciclos ni cambia permisos. | Cubierto automáticamente; repetir aislamiento manualmente. |
| M08 | Abrir portada, esperar sugerencias, escribir, iniciar conversación y pulsar «Explora todas las propiedades». Repetir en móvil y con movimiento reducido. | Ícono de casa, sin rótulo geográfico. Sugerencias cada tres segundos con escritura progresiva, sin alterar lo escrito. Animación detenida al escribir o conversar y omitida con movimiento reducido. Acceso al inventario visible y funcional. | Escritorio revisado. Faltan aceptación de Guillermo, móvil y revisión visual con movimiento reducido. |
| M09 | Despublicar y publicar desde Inventario una propiedad PRUEBA sin citas; consultar búsqueda y ficha. | Cambiar solo publicación, conservar precio y notas. Despublicar excluye de búsquedas nuevas y devuelve 404 en ficha; publicar restaura acceso. Conservar historial previo. | PRUEBA-004 comprobada y restaurada. API, permisos staff y CSRF cubiertos. Falta aceptación de Guillermo. |
| M10 | Despublicar una propiedad de prueba con cita activa; repetir la operación. | Conservar la cita y registrar el aviso sin duplicarlo. No cancelar ni reprogramar automáticamente. | Cubierto automáticamente; prueba manual pendiente con datos aislados. |
| M11 | Combinar texto, publicación, operación, tipo y municipio. Buscar con mayúsculas y acentos, forzar cero coincidencias y limpiar. | Aplicar todos los filtros y mostrar recuento correcto. Buscar por nombre, referencia, colonia, municipio o dirección. Limpiar restaura el inventario. | Referencia, operación y tipo comprobados. Faltan todos los selectores, acentos y aceptación completa. |
| M12 | Abrir enlaces de propiedad y CRM desde otro dispositivo autorizado. | Usar dominio público del piloto. CRM exige acceso del equipo. No exponer notas internas. | Dominio configurado en Docker; falta comprobar acceso externo desde otro dispositivo. |

## Seguimiento: completar antes de cerrar el cuarto incremento

- [ ] M13: sincronizar las tres plantillas y comprobar aprobación de Meta. El estado observado el 7 de noviembre fue PENDING; permanecen desactivadas. La aprobación de Guillermo no equivale a aprobación de Meta.
- [ ] M14: acordar destinatario y texto para un único envío controlado; comprobar entrega y respuesta en CRM. Una autorización técnica puntual no reactiva el ciclo ni elimina una baja.
- [ ] M15: con un caso de prueba y permiso vigente, comprobar selección contextual y días 1, 5, 7, 14, 18, 22, 26 y 28 mediante fechas controladas. No modificar prospectos reales ni esperar 28 días naturales.
- [ ] M16: pedir la baja y volver a consultar. Seguir atendiendo sin reactivar el ciclo. Responder, agendar o pausar durante la preparación impide el envío que perdió pertinencia. Un resultado incierto no se reenvía automáticamente.

M13 y M14 dependen de Meta. Los demás recorridos pueden avanzar sin activar plantillas. Las pruebas con Haiku en base temporal no demuestran entrega real por Meta.

## Repetición por fase

| Fase | Qué comprobar |
| --- | --- |
| Pre-Alpha | Reglas, permisos, presentación y deduplicación automatizados; compilación y proxy. Dobles de proveedores y pruebas opcionales aisladas con Haiku. |
| Alpha | M01–M12 internamente, registrando pendientes. Completar M13–M16 para cerrar el cuarto incremento, aunque Alpha admita funciones incompletas. |
| Beta | Repetir búsqueda → interés → asesor → cita → atención humana → seguimiento con pocos asesores y propiedades reales. Revisar mensajes en móvil, filtros, permisos y duplicados. Inspeccionar fallos en logs. |
| RC | Repetir recorridos críticos en AWS. Comprobar dominio, enlaces, webhook y recuperación tras reinicio. Preservar conversaciones, citas, referencias externas, bajas y trabajos pendientes. No reiniciar ciclos ni reenviar por migrar. Aplicar las comprobaciones de recuperación ya acordadas. |
| GA | Cerrar fallos que pierdan datos, dupliquen acciones o dejen prospectos sin atención. Reutilizar estas regresiones junto con acompañamiento y captación cuando estén implementados. |

## Registro de ejecución

### M25: imágenes y controles de revisión del CRM

Corrección del 7 de noviembre de 2026: imágenes ampliables con navegación y cierre por teclado; explicaciones de verificación humana, excepción geográfica y ubicación pública exacta. Comprobado en el CRM activo con la captación existente, sin aprobarla ni publicarla. Falta repetición en móvil y aceptación de Guillermo. El [diseño de captación](../architecture/captacion/README.md) documenta la auditoría del almacenamiento y los pendientes antes de producción.

### M22: diseño de captación

Pendiente registrado por Guillermo el 7 de noviembre de 2026. Mejorar el diseño del formulario de propietarios. La confirmación de funcionamiento no aprueba su presentación. Falta concretar los ajustes visuales y validarlos en escritorio, tablet y móvil.

### M23: solicitud de cuenta durante captación

Guillermo considera poco amigable la manera actual de pedir crear una cuenta. Rediseñar el momento, la transición y la explicación, conservando datos, fotografías y contexto al registrarse o iniciar sesión. El mecanismo nuevo todavía no está definido; no se elimina el requisito de cuenta.

### M24: flujo completo de cuentas y verificación

Trabajo solicitado para otra etapa: registro, acceso, entrega y verificación real de correo y celular, recuperación, reenvíos y errores. La confirmación del teléfono escrito y un correo guardado localmente no acreditan verificación completa. El [documento de cuentas](../design/cuentas-y-verificacion.md) conserva alcance por definir y criterio de cierre. No implementar como parte de la validación funcional actual ni asignar una fase sin acuerdo.

### M17: conversación expandida

Verificación en navegador de desarrollo del 7 de noviembre. Las casillas completadas registran esa prueba; falta la aceptación de Guillermo.

- [x] Enviar el primer mensaje desde la portada después de elegir una sugerencia. El chat ocupa la altura disponible bajo la cabecera; título inicial e inventario dejan espacio al historial.
- [x] Comprobar «Continuemos la conversación…» y campo de escritura visible al desplazarse por el historial.
- [x] Recargar una conversación existente: restaurar mensajes y vista expandida sin enfocar automáticamente el campo. El teclado físico conserva su prueba pendiente.
- [x] Escribir un borrador, abrir «Propiedades», filtrar y volver. Conservar historial, borrador y filtros durante el cambio de vista.
- [x] Abrir directamente `/#inventario` con una conversación guardada: mostrar inventario y permitir volver al chat.
- [x] Pulsar «Nueva búsqueda»: recuperar portada y sugerencias; una consulta posterior muestra únicamente los mensajes nuevos.
- [x] Abrir contacto de prueba: formulario dentro del historial y campo de escritura visible. Se cerró sin proporcionar celular ni aceptar seguimiento durante M18.
- [ ] Repetir con una propuesta de visita abierta, sin confirmar citas ni permisos reales para comprobar el diseño.
- [x] Repetir con viewports de escritorio, tablet vertical y horizontal y móvil. Las fichas no superan 300 px; móvil conserva el grupo desplazable. El campo quedó visible también con una ventana de 390 × 440 px.
- [ ] En dispositivos físicos, abrir y cerrar teclado, escribir en contacto y cambiar orientación. El campo debe quedar por encima del teclado y los controles deben seguir accesibles.

M17 se valida internamente en Alpha, se repite con asesores en Beta y forma parte del recorrido de conversación en RC y GA. El borrador se conserva al alternar vistas, no al recargar la página. No cambia la fase actual ni cierra el cuarto incremento.

### Regresión responsive del chat, M01 y M02

- [ ] Escritorio: tres fichas en una fila. Mostrar una sola y comprobar que no ocupa el ancho completo.
- [ ] Tablet vertical: dos visibles y tercera accesible al deslizar. Tablet horizontal: tres si caben. Repetir con vista dividida.
- [ ] Móvil: una ficha y parte de la siguiente; deslizar hasta la tercera sin mover horizontalmente toda la página.
- [ ] En los tres tamaños: comprobar foto, nombre, zona, precio, recámaras, baños, estacionamientos, avisos y botones. Ningún dato queda recortado; acciones de al menos 44 px de altura.
- [ ] Usar teclado para enfocar el grupo y desplazarlo. El historial sigue desplazándose verticalmente y el campo permite continuar.
- [ ] Pulsar «Me interesa» en una ficha del chat: registrar la acción sin burbuja artificial ni ficha duplicada. Conservar conversación y borrador. Ver M18 y M19.
- [ ] En una respuesta nueva, registrar interés y preparar contacto: no repetir ficha ni ejecutar esas herramientas durante la corrección del texto.
- [ ] Preguntar precio, mascotas y un dato desconocido; comparar dos opciones. Responder solo lo solicitado, sin forzar fichas adicionales ni inventar datos.
- [ ] Buscar tres propiedades y consultar luego sus detalles: conservar las tres fichas sin duplicarlas ni quedarse solo con la última.

El texto de conversaciones anteriores queda fuera de la corrección; su tamaño de ficha sí cambia. Las pruebas de viewport simulan anchos, pero no sustituyen la aceptación en dispositivos físicos.

### M18: envío directo de «Me interesa»

Verificación del 7 de noviembre en navegador de desarrollo, con una conversación anónima y propiedades PRUEBA. Falta aceptación de Guillermo. Las pruebas de API cubren registro previo al LLM, propiedad exacta, privacidad, deduplicación, CSRF, publicación y conservación de una baja con ciclo cerrado.

- [x] En una ficha del chat, pulsar «Me interesa»: aparece un mensaje nuevo y el formulario de contacto queda disponible antes de la respuesta del modelo, sin pulsar Enviar.
- [x] Dar doble clic: comprobar un único mensaje. Los botones de interés se desactivan durante el envío y la respuesta pendiente.
- [x] Escribir un borrador antes de pulsar la ficha: conservarlo sin enviarlo ni reemplazarlo.
- [x] Pulsar desde inventario y desde ficha pública: restaurar la conversación existente antes del envío automático, o crearla si no existe.
- [x] Recargar después: conservar el mensaje sin repetir el envío iniciado desde el enlace.
- [ ] Simular un fallo de recepción y usar «Reintentar envío»: reutilizar el identificador del mensaje. Si la recepción anterior sí ocurrió, no duplicarla. Ante un fallo de restauración, mostrar error y conservar la conversación guardada.
- [ ] Confirmar que el clic no registra un celular, concede seguimiento ni confirma una cita.
- [x] API: propiedad despublicada rechazada sin crear mensaje ni interés parcial. Un reintento ya aceptado conserva su resultado aunque después se despublique.
- [x] API: autorización por sesión y CSRF. El identificador de propiedad no permite acceder a conversaciones ajenas.

M18 reemplaza el criterio anterior de rellenar el campo. Validar internamente antes de aceptar la mejora y repetirla en Beta y RC.

### M19: interés como acción y continuación humana

Reemplaza el criterio visual de M18 que esperaba un mensaje nuevo del cliente. Las comprobaciones anteriores describen la versión probada entonces; la acción y sus efectos siguen sujetos a deduplicación, permisos y CSRF. El historial previo no se modifica.

- [ ] Desde una ficha del chat, pulsar «Me interesa»: continuar con horarios reales, sin mensaje artificial ni otra ficha.
- [ ] Desde inventario y página de propiedad, entrar a una conversación sin esa ficha: mostrarla una vez y continuar. Recargar no repite la acción ni cambia su visibilidad.
- [ ] Conservar borrador, bloquear doble clic y reintentar con el mismo identificador tras un fallo.
- [ ] Preguntar un dato de una ficha anterior: responder directamente. Pedir verla nuevamente: permitir una ficha nueva.
- [ ] Ignorar la pregunta del nombre y continuar: no volver a preguntar. Dar un nombre: guardarlo sin modificar permisos.
- [ ] Comprobar la frase «Por cierto, ¿con quién tengo el gusto?». Una respuesta fallida o sustituida por otro turno no marca la pregunta como realizada.
- [ ] Sin Google Calendar disponible o sin horarios: explicar la coordinación pendiente sin inventar opciones ni confirmar reservas.
- [ ] Escribir otra petición después del clic antes de la respuesta: atender esa petición, sin imponer una visita.
- [ ] Repetir en escritorio, tablet y móvil, con los mismos límites de ficha y campo de escritura visible.

Verificación del 7 de noviembre: 171 pruebas aprobadas, dos pruebas opcionales omitidas; Ruff, compilación con TypeScript y proxy aprobados. No hay migraciones adicionales pendientes de generar tras `0006_interaction_presentation`.

En navegador, con conversación anónima y propiedad PRUEBA, se comprobó entrada desde inventario, horarios reales obtenidos de Google Calendar, una sola ficha y la pregunta exacta del nombre. Otro doble clic produjo una sola acción adicional oculta, conservó el borrador y no repitió ficha ni pregunta. Recargar conservó ese historial sin mensajes artificiales. No se proporcionó celular ni se confirmó cita o permiso de seguimiento. Evidencia de desarrollo: `/tmp/maia-chat-preview/interest-action.jpg`.

Las pruebas automáticas cubren aislamiento y CSRF, reintentos, despublicación, consulta sin repetir ficha, repetición explícita, nombre conocido o ya solicitado, fallo de respuesta y prioridad de un mensaje escrito después del clic. La aceptación manual de Guillermo y los dispositivos físicos siguen pendientes. Repetir internamente en Alpha y como regresión en Beta y RC.

### M20: atención natural de Maia

Fuentes, decisiones y muestras: [investigación de comunicación humana](../research/comunicacion-humana-2026-11-07.md). Se amplió la skill existente; no cambian estados comerciales ni autorizaciones. Validar en Alpha y repetir en Beta y RC.

- [ ] Corregir compra por renta: reconocer el cambio, conservar zona y presupuesto y no reiniciar el cuestionario.
- [ ] Dar requisitos suficientes: buscar sin volver a preguntar los datos conocidos. Si faltan, plantear una decisión principal por turno.
- [ ] Rechazar compartir celular o nombre: continuar sin presionar ni bloquear la búsqueda.
- [ ] Expresar una preocupación o queja: reconocer el problema concreto, sin entusiasmo automático ni emociones inventadas.
- [ ] Preguntar un dato desconocido: aclarar brevemente y ofrecer una revisión disponible, sin afirmar que ya se pidió.
- [ ] Simular calendario no disponible: evitar horarios inventados y reservas ficticias; ofrecer un siguiente paso real.
- [ ] Preguntar si Maia visitó la casa: identificarla como asistente virtual, sin inventar experiencia propia.
- [ ] Despedirse: cerrar sin nueva pregunta comercial ni presión para visitar.
- [ ] Repetir nombre, citas y presentación M01, M03, M06 y M19. Conservar resultados de herramientas y reglas del canal.

Verificación técnica: 171 pruebas aprobadas, dos opcionales omitidas y Ruff correcto. La prueba opcional de nombre se ejecutó aparte con Haiku y pasó. Se revisaron seis muestras aisladas de redacción sin envíos externos; muestran respeto a negativas, cierres y hechos desconocidos, pero conservan verbosidad en algunos casos. No equivalen a aprobar estos recorridos completos. Aceptación manual de Guillermo, consistencia entre turnos y revisión en website y WhatsApp pendientes.

Anotar ID, fecha, fase, canal o dispositivo, datos PRUEBA, resultado esperado, resultado obtenido y evidencia. Estados: pendiente, aprobado o falló. Repetir los casos afectados después de corregir un fallo. No guardar credenciales en evidencias.

### M21: contrato completo del turno y memoria de continuidad

[Diseño](../design/harness-conversacional.md), [implementación](../design/plan-harness-conversacional.md) y [recorridos manuales](harness-conversacional.md). Probar en Alpha y repetir como regresión en Beta y RC. Los mapas permanecen en `docs/architecture/index.html`.

- [ ] D01–D10 con conversaciones nuevas: una petición principal, cambios de intención, datos conjuntos, contacto por canal y cierre.
- [ ] Clic de interés sin burbuja ficticia ni ficha repetida; nombre contextual, sin apéndice del backend ni formulario que compita con otra pregunta.
- [ ] Recarga conserva datos y pendiente; una entrega fallida o incierta no acredita una pregunta presentada.
- [ ] Website, iPad, móvil y WhatsApp: controles pertinentes y confirmaciones existentes, sin operaciones duplicadas.
- [ ] Revisar especialmente el interés genérico con Haiku: la petición de nombre es preferencia contextual, no un paso impuesto por código.

Verificación técnica: 183 pruebas y una prueba separada de Haiku aprobadas; dos opcionales omitidas en la suite normal. Ruff, Django, TypeScript, compilación y proxy correctos. Migración `0007` aplicada. Las pruebas reales usaron base temporal y no enviaron WhatsApp ni Telegram. Naturalidad comercial y aceptación manual siguen pendientes.

No aprobar una fila completa por probar solo una parte. Ampliar el chat y cambiar su texto inicial siguen como propuestas en las notas de Guillermo; esta lista no las declara implementadas.
