# Validación manual del cuarto incremento

## Aceptación de las pruebas de mensajes, 20 de noviembre de 2026

Guillermo confirmó: «las pruebas de los mensajes resultaron bien». Se registra **aceptación de la prueba técnica comprimida de mensajes y seguimiento**. Las tres plantillas se entregaron y recibieron respuesta en el ciclo 4; los cinco seguimientos de selección contextual se entregaron y alcanzaron `read` en la repetición del ciclo 5, sin errores de entrega. Se conservan los cinco fallos de autenticación de la primera ejecución como evidencia histórica, no como aprobados.

Comprobación a las 22:07: intentos 15–19 del ciclo 5, todos `read`; selección real de `maia_retomar_tipo_municipio` y `maia_retomar_municipio`. Tras el mensaje «Hay algo por Tepatitlan?» de las 21:28, Maia respondió sobre esa zona y el seguimiento de las 21:32 usó «departamento en Tepatitlán», acreditando actualización de variables según la conversación.

El worker cerró automáticamente el ciclo 5 a las **21:37**, retiró el permiso temporal y restauró `contact_opted_out=True`. No hay próximo intento programado. Quedan comprobados recepción de las ocho posiciones del piloto entre ambas ejecuciones, respuestas/continuidad, selección entre alternativas, actualización contextual y cierre/restauración de baja en tiempo comprimido. No equivale a observar 28 días naturales.

Pendientes separados: credencial adecuada para operación continua (el token actual sigue siendo temporal), revisión comercial de textos con Santiago, alerta de seguridad de Next.js y publicar en un PR posterior a #28 los ajustes de aceleración, preflight de credenciales y repetición segura. Guillermo pidió continuar con el PR y dejar la credencial continua y los textos con Santiago para después. La aceptación técnica no aprueba el contenido comercial de las plantillas. El preflight comprueba acceso en ese momento; no garantiza la vigencia futura del token.

Comprobaciones al preparar el PR de continuación: **282 pruebas backend aprobadas, dos opcionales omitidas y 55 pruebas frontend aprobadas**; Ruff, tipos, compilación y proxy real aprobados, sin migraciones nuevas. Se añadió cobertura para repetir fallos de días no consecutivos con intervalos de cinco minutos y evitar crear otra repetición del mismo origen tras cerrar la anterior. El README se actualizó a BETA técnica local; el aviso de seguridad de Next.js sigue como pendiente explícito.

## Fallo de autenticación y repetición de cinco envíos, 20 de noviembre de 2026

Guillermo reportó que no recibió los cinco mensajes acelerados. Revisión a las 21:03: los intentos 10–14 se ejecutaron a las 20:23, 20:28, 20:33, 20:38 y 20:43; Haiku terminó sus cinco selecciones, pero Meta rechazó cada entrega con HTTP 401 (`meta_http_401`). La consulta de catálogo reprodujo `OAuthException`, código 190 y subcódigo 463. Meta informó vencimiento del token a las 18:00 PST, equivalentes a las **20:00 de Guadalajara**. La credencial ya estaba caducada al acelerar el piloto; faltó comprobarla antes del cambio.

El ciclo 4 cerró a las 20:48 y restauró correctamente la baja. Resultado de esa ejecución: **tres plantillas recibidas y respondidas, cinco entregas fallidas**. Su estado técnico `completed` significa que terminó el periodo, no que la prueba haya pasado. Los registros y sus entregas fallidas se conservan sin alteración.

Correcciones: comprobación de acceso a Meta antes de iniciar/acelerar; clasificación explícita de credencial caducada/rechazada; suspensión del ciclo ante un fallo de autenticación, evitando más generaciones y envíos hasta revisión; mensajes de error comprensibles en CRM. El comando de inicio admite `--retry-failed-cycle`: crea otro ciclo solo con entregas conocidas como rechazadas por credenciales; excluye entregas leídas, correctas o inciertas. No reutiliza ni borra intentos del ciclo anterior.

Guillermo actualizó el token. Tras recrear los servicios, la consulta de catálogo y `/debug_token` confirmaron `is_valid=true`, tipo `USER` y vencimiento **20 de noviembre a las 23:00 de Guadalajara**. Sigue siendo una credencial temporal, pero cubre el nuevo tramo. No se imprimieron ni guardaron valores de credenciales en esta evidencia.

Se inició el ciclo **5**, repetición del 4, a las 21:10:54. Solo contiene los días internos 14/18/22/26/28: cinco envíos contextuales, intervalos de cinco minutos, silencio de dos, previstos 21:11:54, 21:16:54, 21:21:54, 21:26:54 y 21:31:54. Cierre/restauración de baja a las 21:36:54, sujetos a la resolución de un minuto del worker. El ciclo 4 permanece cerrado e intacto.

Validación del arreglo: **281 pruebas backend aprobadas y dos opcionales omitidas**, Ruff y reconstrucción estándar de backend/worker/web aprobados, con compilación y tipos frontend. Casos nuevos: detener el ciclo tras credencial caducada, impedir mutación con credencial inválida en ambos comandos, preflight de solo lectura fuera de bloqueos SQL, repetir solo fallos de autenticación conservando historial y no repetir entregas inciertas. Pendiente observar entregas reales de este nuevo tramo.

Primera entrega de la repetición: el worker ejecutó automáticamente el intento **15**, día interno 14 del ciclo 5, y eligió `maia_retomar_tipo_municipio`. Entrega `5e5a65dd-6819-4519-ae34-27fed970472f`: Meta confirmó **`delivered` a las 21:12:55**, con eventos `sent` y `delivered` procesados sin error. Los cuatro intentos restantes continúan previstos hacia 21:17/21:22/21:27/21:32; no se consideran aprobados antes de observarlos. Cierre previsto hacia 21:37.

## Aceleración de los cinco intentos restantes, 20 de noviembre de 2026

Guillermo autorizó explícitamente intentos cada cinco minutos y silencio mínimo de dos. A las 20:21 se reprogramaron solo los cinco intentos todavía sin ejecutar del ciclo 4: 20:22:44, 20:27:44, 20:32:44, 20:37:44 y 20:42:44, hora de Guadalajara. Cierre/restauración de baja a las 20:47:44, con la resolución de un minuto del mantenimiento. Los tres intentos leídos y sus fechas/entregas permanecen intactos. El [plan vigente](seguimiento-piloto-continuo.md) registra el ajuste.

Se añadió el comando explícito `accelerate_followup_pilot`, con persistencia en los metadatos existentes del ciclo. No hay migración adicional ni cambios del calendario de otros prospectos. Validación: **275 pruebas backend aprobadas y dos opcionales omitidas**, Ruff, compilación/tipos frontend, reconstrucción estándar de las tres imágenes y proxy real aprobados. Los tres casos nuevos comprueban conservación de intentos terminados, cadencia/idempotencia, silencio de dos minutos sin afectar ciclos normales y rechazo de reprogramación durante una preparación. La advertencia de seguridad de Next.js ya documentada continúa pendiente.

## Pendiente comercial: rediseñar las plantillas con Santiago

20 de noviembre de 2026. Guillermo confirmó que las plantillas y los mensajes funcionan técnicamente, pero calificó las plantillas actuales como pésimas y señaló que no hacen un buen seguimiento. **La entrega y la continuidad comprobadas no equivalen a aceptar su contenido comercial.**

Queda pendiente discutir el seguimiento con Santiago, quien definirá qué deben decir las plantillas. Revisar con él el propósito y el contenido de cada contacto antes de preparar reemplazos y someterlos a aprobación de Meta. Después de su aprobación, sincronizar y comprobar las nuevas plantillas en Maia. No se reescriben ni se presentan a Meta durante el piloto actual por esta nota; la prueba técnica autorizada continúa con su alcance previo.

## Piloto horario autorizado e iniciado, 20 de noviembre de 2026

Guillermo autorizó expresamente reactivar su número para probar las tres plantillas y la secuencia automática en horas. Se aplicó la migración aditiva `0013` y se inició el ciclo 4 a las 18:47, hora de Guadalajara: ocho intentos cada 30 minutos, primero a las 18:52 y último a las 22:22. Cierre a las 22:32 y restauración de la baja anterior. El [plan actualizado](seguimiento-piloto-continuo.md) detalla límites, textos/plantillas y calendario. No se cancela la cita histórica ni se cambia el horario de otros ciclos.

Las tres plantillas se volvieron a sincronizar con Meta tras renovar la credencial: todas `APPROVED`. Su uso en el piloto es específico de ese ciclo; siguen desactivadas globalmente. Backend, worker y web actualizados; migración aplicada, sin cambios de modelo pendientes y proxy real aprobado. Ningún intento se declaró entregado al programarlo.

Validación final del cambio: **272 pruebas backend aprobadas y dos opcionales omitidas; 55 pruebas frontend aprobadas**, compilación web y tipos aprobados, Ruff y revisión de espacios aprobados. Los once casos nuevos cubren cadencia acotada, aislamiento respecto del calendario normal, tres plantillas sin activación global, worker con un envío por intento, actividad reciente, baja, cierre/restauración de permiso, cambio de destinatario, citas, retirada de aprobación, separación de la intención anterior y ausencia de herencia del permiso temporal a una intención posterior. A las 18:49 se comprobó que el ciclo era elegible, el túnel respondía y la prevención de suspensión seguía activa.

### Primer intento: revisión y corrección

El mantenimiento creó automáticamente el intento 7, día interno 1, a las 18:53. La ejecución 81 eligió `template_id=0` y quedó en revisión sin entrega. Se reprodujo con Haiku real: el contexto completo y también el último intercambio antiguo («Busquemos horarios») producían 0; añadir el permiso vigente no cambiaba el resultado. Sin ese historial anterior al nuevo ciclo, seleccionó la plantilla válida. El perfil piloto había incluido por error todo el historial, mientras los ciclos normales ya delimitaban su intención por `started_at`.

Se añadió una regresión que falló antes del arreglo, se corrigió el límite temporal del contexto y volvió a pasar la reproducción original con Haiku real (ejecución diagnóstica 86), sin crear entregas durante el diagnóstico. El historial anterior se conserva en la base. Se revisó y reencoló **el mismo intento 7** dentro de su ventana, registrando la intervención en actividad del prospecto. La ejecución 87 del worker creó la entrega `b4f933a7-c3f0-42b5-b920-ddb839838dce` a las 18:56. No se alteró el horario de los otros siete intentos. Este primer intento necesitó intervención; no acredita todavía una secuencia entera sin intervención.

Meta confirmó `delivered` a las 18:56:30; los eventos `sent` y `delivered` quedaron procesados sin error. Falta observar la respuesta de Guillermo a esta entrega y los intentos posteriores. El proxy real volvió a pasar tras la corrección.

### Respuesta al primer intento del piloto

A las 19:02:36 Guillermo respondió «Revisemos opciones» (mensaje 176). Maia consultó nuevamente el inventario y respondió con la opción de departamento en renta de Jardines Universidad, conservando Zapopan, presupuesto de MX$25,000, dos recámaras y mascotas, con aviso de propiedad de prueba (mensaje 177). La entrega `85891ab4-992b-43bd-950c-3b50b48ba801` alcanzó `read`, sin error; la primera plantilla también quedó `read`. Comprobación a las 19:03: ciclo 4 abierto, permiso vigente, sin suspensión y próximo intento a las 19:22. La respuesta no movió el calendario. Los intentos posteriores siguen pendientes de observar.

### Segundo intento automático y respuesta

El intento 8 se ejecutó sin intervención manual a las 19:23: plantilla `maia_retomar_municipio`, texto «¿Seguimos buscando en Zapopan o prefieres revisar otra zona?» (mensaje 178). La entrega `df55b093-9e59-46a0-82dd-dd25c2c92eb5` alcanzó `read`, sin error. Guillermo respondió «Aún es Zapopan» a las 19:24:25 (mensaje 179). Maia conservó la zona, explicó que no había más opciones con los requisitos actuales y ofreció ampliar presupuesto o cambiar de zona (mensaje 180); su entrega `a1eecbf2-daba-460a-8c68-dd14b5e50796` también alcanzó `read`, sin error.

Comprobación a las 19:24: dos intentos, ambos leídos, con una entrega de plantilla por intento. Ciclo 4 abierto, permiso vigente, sin suspensión; tercer intento previsto a las 19:52. Ya hay evidencia de un seguimiento posterior completamente automático y continuidad de la conversación; falta la tercera plantilla y los siguientes intentos de selección contextual.

### Tercera plantilla y cobertura de las tres

El intento 9 se ejecutó automáticamente a las 19:53 (ejecución 91), sin intervención manual: `maia_retomar_tipo_municipio`, texto «Retomo tu búsqueda de departamento en Zapopan. ¿Quieres revisar opciones o ajustar lo que buscas?» (mensaje 181). La entrega `e5921bec-31fc-43ff-954f-90ed440fefaa` alcanzó `read`, sin error. Guillermo respondió «Si, sigamos» a las 19:54:19 (mensaje 182). Maia conservó departamento, renta y Zapopan, recordó la única opción disponible con el presupuesto y propuso ajustar presupuesto o zona (mensaje 183). Su entrega `e98a6bd0-9bf5-4cf7-8261-6d2ef9ae2e8c` constaba `delivered`, sin error, en la revisión de las 19:56; no se atribuye lectura todavía.

Quedan comprobadas las tres plantillas aprobadas con variables reales de la prueba, entrega, respuesta entrante y continuación de Maia. Hay tres intentos y una entrega de plantilla por intento; los intentos segundo y tercero se ejecutaron sin intervención. Ciclo abierto, permiso vigente, sin suspensión. Próximo intento previsto a las 20:22; desde ese punto Haiku podrá elegir entre las tres plantillas, en vez de restringir cada intento a una para comprobar cobertura. Siguen pendientes la selección contextual entre alternativas, los cinco intentos restantes y el cierre/restauración de la baja.

La compilación local emitió una advertencia de seguridad sobre Next.js; el reintento y la compilación de la imagen web terminaron correctamente. Queda pendiente revisar/actualizar esa dependencia. La reconstrucción inicial del backend falló por un 403 de un artefacto del lockfile; para arrancar este piloto se reutilizó la imagen existente con las dependencias instaladas y se copió el código actualizado, sin añadir dependencias. Base usada: `sha256:e43e3d985a38fb7b18fdde834daab6d4acef4bdbf0c0ea563a7aa4605353a927`. Al preparar el PR se incorporó la base remota del PR #27, que ya usa dependencias públicas: la comprobación de los 48 paquetes bloqueados y la reconstrucción limpia con el Dockerfile estándar pasaron. El bloqueo 403 quedó resuelto en esa base, sin interrumpir el piloto en ejecución.

## Preparación del piloto continuo, 16 de noviembre de 2026

Configurados prevención de suspensión, arranque al iniciar sesión de OrbStack y túnel, y reinicio de los cuatro contenedores. Se comprobaron recuperación del proceso del túnel y de la web, salud pública y proxy real. La [guía de operación de esta Mac](operacion-continua-mac.md) registra instalación, condiciones y límites. El [recorrido de seguimiento de varios días](seguimiento-piloto-continuo.md) separa la prueba puntual ya aprobada de la ejecución automática pendiente. No se activaron plantillas ni se cambió la baja de Guillermo.

## Plan de prueba completa, acordar inicio

Guillermo pidió comprobar el recorrido completo y los seguimientos de días posteriores. La entrega puntual ya realizada no sustituye la ejecución programada del ciclo.

1. **Disponibilidad:** mantener el equipo encendido, conectado a Internet y sin suspensión, con base, backend, web, worker y túnel activos. Antes de iniciar, comprobar recuperación de servicios/túnel y disponer de una credencial de Meta cuya vigencia cubra la prueba. No atribuir al token renovado una duración todavía no verificada.
2. **Caso de prueba:** acordar número y permiso explícito para el ciclo. El permiso anterior solo cubrió un mensaje. Si se usa el número de Guillermo, revisar desde CRM sus citas/estado antes de reactivar; no cancelar citas, borrar historial, modificar fechas ni sustituir su baja silenciosamente. Registrar nueva intención y requisitos coherentes, identificados como PRUEBA.
3. **Tres plantillas:** comprobar entrega real y variables de cada plantilla aprobada. Solo `maia_retomar_operacion` tiene evidencia de entrega real. Acordar los otros dos textos concretos antes de enviarlos; no asumir que el selector automático elegirá las tres durante un único ciclo.
4. **Ciclo real:** conservar inicio y calendario. Registrar los días 1, 5, 7, 14, 18, 22, 26 y 28, la hora del CRM, selección y variables, intento, entrega y estado en CRM. El silencio de más de 24 horas, permiso y ausencia de suspensión son condiciones para enviar. Si la intención comienza después de la hora de envío, el día 1 puede omitirse por actividad reciente; es el comportamiento esperado, no motivo para alterar fechas.
5. **Continuación:** responder a una entrega y comprobar contexto y respuesta de Maia. Antes de la siguiente fecha, dejar más de 24 horas sin interacción si se espera un envío. Una respuesta reciente debe producir una omisión registrada, sin mover el calendario.
6. **Controles:** comprobar en casos aislados cita, pausa, falta de permiso, baja, cambios durante generación y duplicados. Las 60 regresiones actuales cubren estos controles con reloj/transporte simulados. No modificar el caso principal antes de observar los seguimientos posteriores que se desean comprobar.
7. **Cierre:** separar evidencia real de simulada. Exigir envío programado por worker, respuesta y una entrega de un día posterior; conservar pendientes los días reales todavía no transcurridos. Probar baja al terminar el caso y confirmar ausencia de nuevos envíos. No declarar completados los 28 días por las regresiones ni por un envío manual.

Inspección del 16 de noviembre a las 20:09: cuatro servicios activos; todos con política de reinicio `no`. Túnel `maia-sandbox` activo como proceso; no se encontró un servicio propio de Maia/cloudflared en las carpetas habituales de LaunchAgents/LaunchDaemons consultadas. macOS conserva suspensión por inactividad configurada en alimentación eléctrica (`sleep=1`), con inhibidores temporales activos. No se cambió la energía, el arranque, las plantillas ni los permisos durante esta inspección.

## Regresión del seguimiento automático, 16 de noviembre de 2026

Se ejecutó `tests/test_followups.py` en la base temporal: **60 pruebas aprobadas y una opcional omitida**. Después se ejecutó esa prueba opcional con `MAIA_LIVE_HAIKU_CHECK=1`: **una aprobada con Haiku real**, sin generar entregas WhatsApp. No se cambiaron fechas, permisos o datos del piloto.

La regresión comprueba los días 1/5/7/14/18/22/26/28, horario local y ventana de una hora; omisión de días vencidos; citas, pausa, baja y actividad reciente; selección con datos registrados; cambios durante generación; deduplicación de intentos/eventos y ausencia de reenvío ante resultados inciertos. El calendario y transporte se simulan en estas pruebas; la selección con Haiku real usa una plantilla de prueba y no acredita por sí sola la selección entre las tres de Meta.

Consulta de operación a las 20:07 (America/Mexico_City): las tres plantillas aprobadas mantienen variables correctas y están desactivadas. Hay dos ciclos abiertos, ambos sin permiso; uno suspendido por cita. El prospecto de Guillermo conserva baja y cero ciclos abiertos. No se hicieron envíos adicionales. Siguiente decisión: habilitar las tres plantillas para prospectos con permiso vigente, conservando las bajas. La ejecución programada real con selección automática sigue pendiente de un caso autorizado y elegible.

## Respuesta y continuación confirmadas, 16 de noviembre de 2026

Guillermo respondió «Si» a la plantilla a las 20:05. El webhook entrante (evento `88`) quedó procesado sin error; el mensaje `171` se registró en la conversación WhatsApp existente. Maia continuó con el contexto de renta previo y guardó el mensaje `172`. Su entrega `17dfb4af-976f-4447-8165-0391c28cf9da` alcanzó `read`, sin errores, a las 20:05 (America/Mexico_City). La plantilla de prueba también alcanzó `read`.

Queda comprobado el recorrido real de plantilla autorizada → entrega → respuesta entrante → continuación de Maia → entrega de la respuesta, con registro en CRM. Se verificó nuevamente `contact_opted_out=True`. El incremento 4 conserva pendientes la activación acordada de plantillas y la validación del seguimiento automático: selección contextual, calendario, omisiones, baja y ausencia de duplicados. Esta prueba puntual no cierra esos casos.

## Entrega controlada confirmada, 16 de noviembre de 2026

Guillermo autorizó su número personal registrado en el CRM y el texto «Sobre tu búsqueda para rentar, ¿quieres revisar opciones o cambió lo que necesitas?». Se envió una sola plantilla `maia_retomar_operacion`, `es_MX`, variable `1=rentar`, mediante la cola y transporte existentes. Entrega `72e549c2-035a-4c48-9cb3-119c0fcba31b`, con clave única de prueba para impedir duplicados. Meta aceptó el envío a las 20:04 y el webhook registró `delivered` a las 20:05 (America/Mexico_City); los eventos quedaron procesados sin error.

El mensaje y su entrega están vinculados a la conversación WhatsApp del CRM. Se comprobó que `contact_opted_out=True` permanece intacto; no se activaron plantillas ni ciclos. Es una prueba puntual autorizada de entrega, no una validación del calendario o selección automática del seguimiento. Falta comprobar la respuesta del usuario y la continuación de Maia, además de los demás casos del seguimiento real.

## Sincronización confirmada, 16 de noviembre de 2026

Tras renovar la credencial y recrear backend/worker conservando los proveedores de correo y mapas, la sincronización real de Meta terminó correctamente a las 20:00 (America/Mexico_City). Las tres plantillas `maia_retomar_tipo_municipio`, `maia_retomar_municipio` y `maia_retomar_operacion`, idioma `es_MX`, tienen estado `APPROVED` en CRM. Conservan sus variables y `enabled=False`.

Queda comprobada la aprobación y sincronización. Pendientes: acordar destinatario y texto de la prueba controlada, activar las plantillas que correspondan y validar entrega, respuesta y seguimiento real. No se enviaron mensajes ni se reactivaron ciclos; se conserva la baja de Guillermo.

## Consulta de Meta, 16 de noviembre de 2026

La consulta real del catálogo devolvió HTTP 401, `OAuthException`, código `190` y subcódigo `463`: el token de acceso caducó. No se pudo comprobar la decisión de Meta ni sincronizar el catálogo. Las tres plantillas de Maia siguen en CRM con el último estado guardado `PENDING`, sincronizado el 7 de noviembre, y `enabled=False`. Ese estado no acredita que sigan pendientes en Meta.

Siguiente paso: renovar la credencial configurada y repetir la consulta/sincronización. No se enviaron mensajes, activaron plantillas ni reactivaron ciclos.

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
