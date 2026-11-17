# Validación manual del cuarto incremento

## Actualización de Guillermo, 7 de noviembre de 2026

Guillermo confirmó que las pruebas del incremento 4 funcionan y priorizó el incremento 6, captación de propiedades, mientras Meta aprueba las plantillas. El incremento 5 queda pospuesto. Se registra su aceptación general de las pruebas realizadas; las casillas anteriores conservan su alcance histórico, sin atribuir nuevas ejecuciones individuales.

Pendientes para cerrar el incremento 4:

- [ ] Comprobar aprobación de las tres plantillas en Meta y sincronizar su estado en CRM. El último estado documentado es `PENDING`; no se consultó Meta en esta actualización.
- [ ] Revisar variables y activar las plantillas aprobadas que correspondan.
- [ ] Acordar destinatario y texto de un envío controlado; verificar entrega, respuesta y registro en CRM con permiso vigente.
- [ ] Completar la validación real del seguimiento con plantillas: selección contextual, días acordados, omisiones, baja y ausencia de duplicados. Las pruebas locales aprobadas no acreditan todavía este envío real.

La baja existente de Guillermo se conserva. Esta nota no autoriza envíos ni reactivación de su ciclo. Se inicia el [diseño del sexto incremento](../design/sexto-incremento-captacion.md); el cuarto conserva estos pendientes y no se declara el paso a Beta.

## Registro previo a esta confirmación

Actualización del harness: el [nuevo contrato conversacional](harness-conversacional.md) sustituye la pregunta de nombre añadida, los horarios forzados por clic y la corrección anterior de texto. Su evidencia vigente es 183 pruebas, Haiku real separado, compilación y proxy, con migración `0007`. Los registros siguientes conservan la evidencia histórica del incremento; no acreditan aceptación manual del rediseño.

Estado: cuarto incremento en validación. Guillermo confirmó la primera conversación real por WhatsApp: recepción, respuesta, entrega y registro en CRM. Los casos restantes y la entrega de seguimientos con plantillas siguen pendientes. Consulta las [mejoras y regresiones por fase](mejoras-transversales.md).

Guillermo también validó creación, reprogramación y cancelación de citas por WhatsApp. Solicitó un tono más humano tras la cancelación: se añadió la skill obligatoria `comunicacion-humana`, complementaria a `comunicacion-cliente`, y se ajustaron los mensajes automáticos. Después aprobó la presentación y el tono de los ajustes del website, WhatsApp y Telegram.

Verificación automatizada actual: 162 pruebas aprobadas y dos pruebas opcionales de Haiku omitidas. Incluye días del ciclo, omisiones, contexto, permisos, deduplicación, confirmación de citas, entregas inciertas, formatos mexicanos `52`/`521`, fichas de WhatsApp, corrección limitada de texto duplicado, avisos de citas sin intereses registrados, captura del nombre y publicación desde el inventario. Añade respuestas concretas sin ficha, corrección de texto tras preparar contacto sin repetir acciones, conservación de tres resultados al consultar sus detalles y registro determinístico del clic de interés. El frontend compila. Las respuestas de Meta y Google de estas pruebas son controladas; la entrega real se comprobó por separado con el número de prueba de Meta.

## Inventario del CRM

Cada fila permite publicar o despublicar sin abrir el editor. Los filtros combinan texto (nombre, referencia, colonia, municipio o dirección), publicación, operación, tipo y municipio. La búsqueda ignora mayúsculas y acentos; muestra el recuento y permite limpiar los filtros.

Verificación en Chrome: búsqueda por referencia, filtros combinados de operación y tipo, estado sin coincidencias, despublicación y publicación de `PRUEBA-004`. Su ficha pública respondió 404 al despublicar y 200 al restaurarla. Esa propiedad no tenía citas activas y quedó publicada como al inicio. La revisión automatizada restante del menú nativo se interrumpió; falta la aceptación de Guillermo de todos los filtros.

Las pruebas de API comprueban acceso staff, CSRF, rechazo de campos ajenos a la publicación, conservación de precio y notas actuales, visibilidad pública y aviso de citas sin cancelarlas. OpenAPI y sus tipos del frontend están actualizados; no hay migraciones nuevas.

## Presentación acordada

Conversación expandida implementada: primer envío y restauración al recargar ocupan la altura disponible bajo la cabecera; el campo muestra «Continuemos la conversación…». Navegación al inventario y regreso conservan conversación, borrador y filtros sin desmontar los componentes. «Nueva búsqueda» recupera la portada. Contacto, permisos, visitas y avisos quedan dentro del historial desplazable.

Compilación y TypeScript aprobados; proxy HTTP comprobado. Revisión de escritorio, tablet vertical y horizontal y móvil, incluido un viewport de altura reducida: campo visible, fichas de hasta 300 px y distribución de tres, dos o una según el ancho. La restauración no enfocó el campo. Contacto abierto revisado durante M18; la [prueba M17](mejoras-transversales.md#m17-conversación-expandida) conserva pendientes de propuesta de visita abierta, teclado físico y aceptación de Guillermo. La vista expandida no modifica backend ni contratos HTTP; M18 añade el campo opcional de interés descrito abajo.

Fichas compactas adaptadas al ancho del chat: tres columnas desde 900 px disponibles, dos desde 560 px y una con parte de la siguiente por debajo. Cada ficha conserva un máximo de 300 px y no llena la fila al estar sola. El umbral pasó de 720 a 900 px con la vista expandida para mantener dos fichas en tablet vertical. Se conserva el contenido en todos los tamaños, con acciones de al menos 44 px y desplazamiento horizontal manual dentro del grupo. Los mensajes guardados conservan su texto. La [regresión responsive](mejoras-transversales.md#regresión-responsive-del-chat-m01-y-m02) incluye escritorio, tablet, móvil, teclado y preguntas concretas.

Prueba real en el website: la búsqueda devolvió tres fichas sin repetir sus datos en el texto. Se corrigió un fallo observado: llamadas posteriores a `get_property` reemplazaban las fichas y dejaban solo la última. Ahora actualizan la ficha correspondiente sin perder las demás. Viewports de 1440, 768 y 390 px comprobaron tres, dos y una ficha visible respectivamente; móvil no desbordó horizontalmente la página y el grupo respondió al teclado. Falta aceptación de Guillermo y prueba táctil en dispositivos físicos.

La primera implementación de «Me interesa» solo rellenaba el campo. Guillermo rechazó ese segundo paso durante las pruebas: ahora el clic envía el mensaje directamente desde chat, inventario y ficha pública. Se conserva el borrador existente dentro del chat y se comparte el envío con protección frente a llamadas simultáneas y reintento con el mismo identificador. La [prueba M18](mejoras-transversales.md#m18-envío-directo-de-me-interesa) registra su validación.

La primera prueba de envío directo mostró que el modelo todavía preguntaba si debía registrar interés. Se corrigió en la recepción del mensaje: `property_id` opcional identifica la propiedad y el código registra el interés antes del LLM. El servidor construye el texto con el título vigente, sin IDs visibles; el contexto conserva una referencia autorizada. OpenAPI y tipos actualizados, sin migraciones nuevas.

Repetición en navegador aprobada: doble clic produjo un mensaje, conservó un borrador distinto y habilitó contacto inmediatamente; inventario y ficha pública enviaron sin otro clic en Enviar. Restauraron la conversación existente y funcionaron también sin una conversación previa. Recargar no duplicó el mensaje. El formulario de contacto abierto quedó dentro del historial, con el campo de escritura visible; se cerró sin proporcionar celular ni aceptar seguimiento. Aceptación final de Guillermo pendiente.

La pregunta real por la renta de Ciudad Granja recibió precio y aviso de prueba, sin recámaras, baños, estacionamientos ni otra ficha. Una primera respuesta había añadido esos datos: se reforzó la indicación de presentación de `get_property(show_card=false)` antes de repetirla. Esa prueba no registra contacto ni envía avisos a asesores.

Portada actualizada: ícono de casa en el campo, sin el texto superior de la zona metropolitana, sugerencias con escritura progresiva que rotan cada tres segundos y acceso destacado «Explora todas las propiedades». La animación se detiene al escribir o tener conversación y se omite con movimiento reducido. Compilación aprobada y revisión en Chrome de escritorio: ícono, ausencia del texto, escritura progresiva, conservación de lo escrito y enlace al inventario. No se enviaron consultas durante esta revisión. Falta la aceptación visual de Guillermo de esta portada.

- Website y WhatsApp muestran hasta tres propiedades con nombre, precio, zona y hasta tres características pertinentes. Conservan los avisos de prueba y datos por confirmar. El agente escribe la introducción; el canal presenta las fichas y coloca la pregunta final después de ellas.
- Si una respuesta exclusivamente de inventario repite nombres, referencias, precios o especificaciones detectables, el harness pide una corrección sin herramientas. Si vuelve a fallar, usa una introducción fija. Los logs registran `property_copy_repair` y `property_copy_fallback`. La comprobación no reescribe resultados de acciones comerciales.
- Telegram distingue información de solicitudes de atención. Los avisos de citas conservan propiedad, evento y horario legible del momento de la notificación, sin depender de intereses ni mostrar campos vacíos. Un reintento conserva esos datos.
- Docker Compose usa `https://sandbox.elmenlabs.com` para los enlaces públicos. La ejecución nativa conserva `PUBLIC_BASE_URL` configurable.
- [x] Presentación de búsquedas en website y WhatsApp aprobada por Guillermo.
- [x] Presentación y tono de los avisos de citas en Telegram aprobados por Guillermo.
- [x] Solicita atención humana y comprueba que Telegram indica que requiere atención. Validado para website y WhatsApp por confirmación manual de Guillermo el 7 de noviembre.

La búsqueda real con Haiku, a través del proxy del website, devolvió una ficha y el texto: «Esta es la opción que encontré con tus criterios. ¿Quieres más detalles de alguna?». No repitió precio, nombre ni aviso de prueba. Guillermo aprobó la presentación y el tono de estos ajustes. No se reenviaron notificaciones históricas.

## Preparación

- [ ] Completa [WhatsApp del piloto](whatsapp-setup.md). Comprueba cuenta, número, versión, firma, webhook y recepción real.
- [ ] Sincroniza plantillas aprobadas desde CRM → Prospectos → WhatsApp y reglas de seguimiento. Asigna variables y activa las plantillas pertinentes.

Las tres plantillas aprobadas por Guillermo se crearon en Meta el 7 de noviembre: estado observado `PENDING`, sincronizadas al CRM y con variables asignadas. Permanecen desactivadas. Falta la decisión de Meta y la prueba de entrega controlada.

La prueba opcional `test_real_haiku_selects_a_grounded_template_without_sending` se ejecutó por separado el 7 de noviembre y pasó con la API real de Haiku. Usó una plantilla de prueba en la base temporal, no las tres pendientes en Meta; comprobó selección, registro de tokens y ausencia de entregas WhatsApp.

Para la entrega real: comprobar aprobación, acordar destinatario y texto, registrar un único envío y verificar su estado y la respuesta en CRM. La baja de Guillermo se conserva. Un envío técnico a su número requiere autorización explícita para ese mensaje y no reactiva el funnel; la validación completa del ciclo usa un caso con permiso vigente.

- [ ] Usa un destinatario acordado y datos identificados como PRUEBA. Conserva las citas y prospectos reales.

## Conversación y citas

### Nombre del cliente

Maia responde primero sobre la propiedad concreta y pregunta el nombre si no lo conoce ni lo preguntó antes. El nombre es opcional: ignorarlo no detiene la atención. Las búsquedas vagas y las solicitudes urgentes se atienden primero.

`record_name` guarda el nombre expresado sin iniciar interés ni cambiar permisos. WhatsApp actualiza también la ficha del prospecto. En website, el nombre queda en su conversación y se prepara para el formulario; declarar un celular no permite sobrescribir el nombre de otra ficha del CRM. El nombre conocido se incluye en el contexto del agente.

La prueba opcional con Haiku real pasó en la base temporal: consulta de una propiedad, pregunta del nombre, respuesta «Me llamo Guillermo», persistencia y siguiente respuesta sin volver a preguntarlo. No envió WhatsApp ni reactivó el seguimiento.

- [ ] Consulta una propiedad sin nombre conocido: Maia responde y pregunta cómo te llamas.
- [ ] Da tu nombre: aparece en CRM y Maia continúa sin volver a pedirlo.
- [ ] Ignora la pregunta: Maia sigue respondiendo sin insistir.

Desde `backend`, sin envíos reales:

```bash
MAIA_LIVE_HAIKU_CHECK=1 uv run --frozen python -m pytest tests/test_contact_name.py::test_real_haiku_handles_interest_interruption_and_name_without_sending -q
```

### Confirmación de visitas

Hallazgo del 7 de noviembre: al elegir un horario para reprogramar, Maia anunció un botón sin llamar a `prepare_visit`. Se añadió una corrección limitada a un intento cuando la respuesta pide un botón de cita y no existe una propuesta vigente sin confirmar. Si el modelo repite el fallo, se envía un error sin prometer el botón. Las pruebas cubren reprogramación, cancelación y fallo persistente. Guillermo confirmó después que la reprogramación y la cancelación funcionaron. Repetir el botón y comprobar aislamiento entre conversaciones conservan su validación específica en la lista.

- [ ] Escribe por WhatsApp. La conversación aparece en CRM con su canal, requisitos, propiedades y responsable. Maia responde sin volver a pedir el celular.
- [ ] Busca con una petición vaga y después precisa requisitos. Maia pregunta solo lo que falta y consulta inventario vigente.
- [ ] Pide visitar una propiedad conocida sin indicar fecha. Maia ofrece hasta tres horarios reales.
- [ ] Elige un horario. WhatsApp muestra propiedad, asesor, fecha, duración y botón. Antes del clic no existe reserva.
- [ ] Confirma con el botón. La cita aparece en Google y CRM; WhatsApp comunica el resultado verificado. Repetir el botón no crea otra cita.
- [ ] Cancela y reprograma desde WhatsApp con confirmación explícita. Otra conversación no puede usar el identificador de esa propuesta.
- [ ] Envía un audio. Maia pide texto y no inventa una transcripción.

## Inicio, permisos y contexto

Hallazgo del 7 de noviembre: «No quiero recibir más mensajes» produjo una confirmación sin ejecutar la baja. Se añadieron las variantes con «más» y «mas» a la ruta determinística y se reforzó la obligación de ejecutar `stop_followup` antes de confirmar bajas interpretadas por el modelo. Se aplicó la solicitud ya recibida: permiso desactivado, ciclo cerrado por `opted_out` y ningún ciclo abierto. La regresión comprueba también que una búsqueda posterior no reabre el ciclo; esa continuación real sigue pendiente.

- [ ] Desde website, busca y expresa interés sin dar celular. Continúa conversando sin registro de identidad ni envío WhatsApp.
- [ ] Confirma el celular con permiso de seguimiento desmarcado. El CRM conserva el interés y el inicio original; no autoriza seguimientos WhatsApp.
- [ ] Acepta el seguimiento desde el website. El CRM refleja el permiso. No se reinicia el ciclo ni se recuperan días anteriores.
- [ ] Llega desde WhatsApp y expresa una búsqueda comercial. El CRM registra un ciclo con el permiso por defecto acordado, salvo baja previa. Una conversación exploratoria posterior no inicia otro ciclo.
- [ ] Recibe una reactivación contextual y contesta por WhatsApp. Maia retoma el contexto autorizado de esa intención, sin pedir de nuevo datos conocidos. El website de otro visitante no recibe ese historial por compartir un celular declarado.
- [ ] Pide dejar de recibir mensajes. Se cierra el ciclo y se registra la baja. Una nueva consulta recibe respuesta sin reactivar automáticamente el seguimiento.

## Calendario y control humano

- [ ] Configura la hora desde CRM. El horario usa Guadalajara y una ventana de envío de una hora.
- [ ] Comprueba inicio, fin, próximo día del ciclo y resultados por intento en la ficha del prospecto. No se añaden etapas comerciales por estados de entrega.
- [ ] Agenda una cita: el ciclo queda suspendido. Cancelarla o registrar la visita no reactiva los mensajes por sí solo.
- [ ] Reactiva desde CRM después de resolver citas y pausa: conserva las fechas originales y solo quedan disponibles los días restantes.
- [ ] Marca Sin interés: cierra el ciclo. Volver a En atención no lo reinicia.
- [ ] Tras terminar el ciclo y recibir una nueva interacción, confirma Nueva intención desde CRM. Conserva el ciclo anterior. Una baja requiere nuevo permiso explícito.

Los días 1, 5, 7, 14, 18, 22, 26 y 28, el vencimiento de una hora y las carreras durante generación se comprueban automáticamente, sin esperar 28 días ni modificar fechas de prospectos reales.

## Avance independiente de Meta

Preparación comprobada el 7 de noviembre: backend y worker activos, Telegram configurado y asesor predeterminado con chat. La conversación WhatsApp del piloto no estaba pausada ni tenía solicitud humana pendiente. La baja seguía vigente, sin ciclos abiertos y con las tres plantillas desactivadas. Pasaron las 29 pruebas de `tests/test_prospects.py`, con transporte controlado; no acreditan la entrega real de esta prueba.

Resultado del 7 de noviembre: Guillermo confirmó exitosos solicitud humana con aviso Telegram, pausa sin respuesta y reactivación ante un mensaje nuevo, sin respuesta atrasada. Confirmó también WhatsApp como funcionando, por lo que M05 queda aprobado para ambos canales mediante validación manual. El aviso reciente observado en registros consta `sent`, originado en website a las 16:41 de Guadalajara; no se presenta como evidencia técnica del recorrido WhatsApp. La recepción Telegram y la pausa/reactivación en WhatsApp se sustentan en la confirmación de Guillermo.

Comprobación posterior: conversación y prospecto WhatsApp sin pausa, baja vigente, permiso de seguimiento desactivado, ningún ciclo abierto y las tres plantillas desactivadas. No se modificaron permisos ni se reenviaron avisos durante esta comprobación.

Mientras las plantillas estén pendientes, validar primero el control humano: solicitar un asesor, comprobar el aviso de atención en Telegram, pausar Maia desde CRM, enviar una consulta y comprobar que queda registrada sin respuesta automática. Al reanudar desde CRM, enviar otra consulta y comprobar que Maia responde. La baja de seguimientos debe permanecer activa durante toda la prueba.

Después, validar desde otra sesión del website la exploración sin celular y la captura de contacto sin permiso de seguimiento. Conservar separadas las conversaciones y comprobar en CRM que no se habilitan mensajes WhatsApp. No aceptar el permiso en el prospecto de Guillermo mientras su baja forme parte de la prueba.

## Revisión y fallos

- [ ] Sin plantilla aprobada que pueda completarse con datos reales: no enviar; mostrar revisión en CRM.
- [ ] El prospecto responde, agenda o el asesor pausa mientras se prepara el mensaje: omitir el envío desactualizado.
- [ ] Revisa mensajes bloqueados, rechazados o inciertos en WhatsApp y reglas de seguimiento. Un mensaje incierto no ofrece reenvío automático.
- [ ] Reintenta una entrega rechazada conocida dentro de su ventana vigente. Conserva el texto; no vuelve a llamar al modelo. Revalida permiso y pertinencia.
- [ ] Un mensaje aún no enviado no aparece como respuesta entregada en el website. El CRM conserva texto y estado de entrega.

## Comandos de verificación

Desde `backend`:

```bash
uv run --frozen pytest -q
uv run --frozen python scripts/check_web_routes.py
```

Prueba opcional con la API real de Haiku, aislada en la base de pruebas y sin envío WhatsApp:

```bash
MAIA_LIVE_HAIKU_CHECK=1 uv run --frozen pytest tests/test_followups.py::test_real_haiku_selects_a_grounded_template_without_sending -q
```

Ejecuta ambas invocaciones de pytest en serie: comparten la base temporal. Revisa ejecuciones con `docker compose logs -f backend worker`.
