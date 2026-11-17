# Validación del incremento 6: captación

## Actualización del 15 de noviembre de 2026

Resend quedó activado en backend y worker. La comprobación de configuración informó `ready: true`, sin incidencias, y `webhook_ready: true`. Se arrancaron la plataforma y el túnel; la web pública respondió HTTP 200. Guillermo confirmó que funciona el envío real de aprobación. Esa confirmación no acredita por sí sola aceptación, publicación ni recepción del evento firmado `delivered`.

El recorrido vigente para cerrar los pendientes es la [guía de cierre del incremento 6](cierre-incremento-6.md), con pasos, resultados esperados y separación entre pruebas manuales y técnicas. Las menciones siguientes de correo local o activación pendiente conservan el estado histórico del trabajo nocturno, anterior a esta actualización.

Implementación local del 7 de noviembre de 2026. Alcance funcional confirmado por Guillermo; aceptación manual del incremento todavía pendiente. El cuarto conserva sus pendientes de Meta. El quinto permanece pospuesto.

## Punto para retomar después del trabajo nocturno

**Punto actual para retomar, 15 de noviembre de 2026:** Guillermo estaba en la **prueba 5**, ubicación/guardar y recuperar borrador. Se implementó la integración opcional Google Places/Maps con resultados temporales separados y alternativa manual. Claves y comprobación real con Google pendientes. Seguir el [recorrido manual actualizado](sexto-incremento-recorrido-manual.md) y la [activación de Google](google-ubicacion-beta.md). La prueba 11 se adapta al contacto por WhatsApp y acciones CRM porque el formulario del propietario fue eliminado por solicitud de Guillermo.

Actualización del 15 de noviembre de 2026: Resend está activado en backend y worker. Guillermo confirmó recepción del correo de aprobación; el registro de entregas contiene una confirmación `delivered`. La recuperación desde el dominio público fallaba con HTTP 403 porque faltaba `https://sandbox.elmenlabs.com` en `CSRF_TRUSTED_ORIGINS`. Se añadió ese origen explícito en Compose, conservando localhost. Comprobación HTTP con sesión y token CSRF válidos: recuperación desde el origen público pasa de 403 a 200; un origen ajeno sigue rechazado con 403. Se usó un correo inexistente para no enviar mensajes durante esa comprobación. Falta que Guillermo repita la recuperación real y cambie su contraseña; tampoco se da por confirmada la aceptación ni publicación de la captación.

Guillermo pidió avanzar dentro del incremento 6 y dejar preparada la integración con Resend. No se añadieron funciones del quinto incremento ni verificación SMS de la etapa posterior.

1. Completar la activación de Resend con [la guía para BETA](resend-beta.md). El dominio `maia.elmenlabs.com` quedó verificado el 15 de noviembre de 2026, con Forge Ready. Faltan remitente, clave de envío, webhook y activación en Maia; la instancia sigue usando correo local. El asistente `scripts/setup-resend-beta.sh` prepara la configuración en un archivo privado.
2. Después de configurar el proveedor, abrir la captación aprobada en el CRM y usar «Enviar correo con el proveedor configurado». Ahora puede encolar el aviso que quedó `stored`, sin volver a aprobar ni duplicar una entrega conocida. No hay envío masivo automático. Comprobar recepción del PDF, liga y confirmación del servidor del destinatario.
3. El propietario debe entrar desde el correo, revisar y aceptar el dummy de exclusividad por seis meses. Después el equipo actualiza el CRM y publica. La captación del piloto sigue aprobada, sin aceptar ni publicar; el asistente no realizó esas acciones por el propietario.
4. Revisar las mejoras de cuenta y móvil. Ahora se explica por qué se pide registro, se conserva el formulario al volver y se enfoca la sección correcta. Se corrigió un destino anterior que podía reaparecer al empezar otra propiedad. La descarga privada del contrato está disponible desde la solicitud y conserva la copia aceptada.

Última suite completa: **230 pruebas aprobadas y dos opcionales omitidas**. Incluye 14 casos de Resend con transporte simulado: adjunto, idempotencia, rechazos, incertidumbre, firmas, eventos duplicados/desordenados, confirmación anterior a la respuesta HTTP y envío de correo local tras configurar proveedor. También prueba privacidad e inmutabilidad de PDF, auditoría sin reparación y compresión al girar fotos. Seis pruebas del chat, tipos y compilaciones aprobados.

Se inspeccionaron los PDF de revisión y aceptación, ambos de una página. Se probó la descarga en navegador con cuenta aislada. Registro y contrato no desbordaron a 390 px; el formulario tampoco a 768 px. Se verificó que volver desde registro conserva Renta. La cabecera de propietarios ya distribuye sus enlaces sin superponer el logo en móvil. Evidencia local: `/tmp/maia-crm-review/beta-cuenta-movil.png` y `/tmp/maia-crm-review/beta-contrato-movil.png`. Falta aceptación de Guillermo y repetición en dispositivos físicos.

Backend, worker y website actualizados conservando volúmenes; migración `0010` aplicada. Auditoría de la instancia activa: cinco archivos comprobados, cero errores y cero huérfanos. El aviso del piloto sigue `stored`, revisión 14, con cero acuerdos aceptados y propiedad no publicada. El proxy real pasó su comprobación. «Ya tengo cuenta» ahora abre inicio de sesión; se comprobó en navegador que ya no abre registro.

Los procesos temporales de 8101/3301 quedaron detenidos. La base aislada conserva solo registros de prueba. Las pruebas de aceptación del dummy que generaron ejemplos PDF se hicieron en esa base, no sobre la propiedad del piloto. La comprobación móvil confirmó el acuerdo a 49 px del borde superior, sin desbordamiento y sin superposición entre logo y navegación. Recargar `http://localhost:3000/crm` y `/propietarios` para recibir la versión nueva en pestañas que quedaron abiertas.

Pendientes externos: cuenta/dominio/remitente y claves de Resend, entrega real y DNS, aceptación del propietario, prueba de publicación con Guillermo, respaldo externo y restauración conjunta. La auditoría de archivos ya puede ejecutarse sin modificar ni borrar datos con `python manage.py check_capture_storage --verify-images --find-orphans`. El flujo completo de cuentas/verificación de celular sigue pendiente en otra etapa. El incremento 4 espera Meta; el 5 está pospuesto; estamos en el 6. No se hicieron commits, pushes ni cambios de rama.

## Recorrido disponible

Website → «Vende o renta tu propiedad» (`/propietarios`): Venta, Renta y Preventa; 19 tipos con sus subtipos, ubicación nacional, características, fotos y planos, comodidades, vista previa y envío.

La cuenta requiere email, teléfono y contraseña. Verifica el email antes de enviar. El teléfono se confirma como bien escrito, sin SMS. Se permite empezar antes de registrarse y guardar borradores incompletos; para enviar se necesitan cinco fotos. La plataforma reduce imágenes, corrige orientación y elimina metadatos. Admite HEIC, fotos comunes y planos PDF o imagen; originales no se publican. Portada, orden, giro, eliminación y reintento por archivo están disponibles.

CRM → Captación: revisar datos privados, corregir, confirmar representación y aprobación fuera de la zona base, asignar asesor y aprobar. Una corrección vuelve a revisión e invalida la aceptación anterior. El propietario acepta el dummy desde su cuenta; luego el equipo publica. Los seis meses empiezan al aceptar. Al vencer o cancelar, se despublica y conserva historial y citas. Las retiradas y renovaciones se solicitan desde la cuenta; el asesor resuelve. Renovar exige otra aceptación.

## Puesta en servicio

1. Reconstruir backend, worker y website. La migración `0008_capture_owner_intake` se aplica mediante el arranque Docker existente. Fuera de Docker, ejecutar `uv run --directory /Users/el-men/Workspace/maia-agent/backend --frozen python manage.py migrate` y arrancar los tres procesos con la versión nueva.
2. Conservar los volúmenes `capture_media` y `private_mail`. No usar una orden que elimine volúmenes para actualizar.
3. Configurar correo para recibir verificación y recuperación reales. Sin configuración, el backend de desarrollo guarda correos en `backend/private-mail` o `/app/private-mail` dentro del worker, no los entrega al destinatario. Esos archivos contienen enlaces de acceso y son privados.
4. Para SMTP, configurar `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` y `DEFAULT_FROM_EMAIL` en backend y worker. Configurar un remitente permitido por el proveedor. No compartir credenciales en el chat.
5. Comprobar `PUBLIC_BASE_URL`: los enlaces del correo y las fotografías deben usar el dominio de la instancia. El worker debe estar actualizado para procesar avisos y vencimientos.
6. Reenviar verificación desde la cuenta cuando el correo esté configurado. El código no omite verificación para compensar un proveedor ausente.

La validación inicial usó la base temporal de pruebas y dos procesos en puertos 8101/3301, sin worker ni credenciales activas de proveedores. Esos procesos se retiraron después de verificar. Los registros PRUEBA no pertenecen al inventario del piloto.

Actualización del 7 de noviembre de 2026: Guillermo reportó HTTP 404 en `http://localhost:3000/propietarios`. La imagen activa del website no incluía la ruta. Se reconstruyeron y actualizaron backend, worker y web; se aplicó la migración `0008` conservando la base y los volúmenes. La instancia activa ya responde HTTP 200 en `/propietarios`, `/api/capture/catalog`, `/api/capture/account` y `/api/health`. El catálogo devuelve 19 tipos y el proxy del chat pasó su comprobación. No se creó una cuenta ni se envió una captación para esta comprobación. La configuración y entrega real de correo conservan su validación pendiente.

## Evidencia técnica

### Correo de aprobación y contrato PDF, 7 de noviembre de 2026

Al aprobar o preparar renovación se encola un correo al propietario con contrato dummy PDF y liga directa a su solicitud. Se conserva una copia versionada para generar el adjunto; se evita duplicar el evento y no se reintentan envíos inciertos. Una aprobación sustituida se descarta antes del envío. El correo local aparece como «Guardado en correo local; no entregado al cliente» en el CRM.

Migración nueva: `0009_capturedelivery_attachment`. La copia del contrato usa JSON y el PDF se genera en el worker; el mensaje completo con adjunto queda en correo local cuando ese es el backend configurado. No se configura un proveedor externo como parte de este cambio.

213 pruebas aprobadas y dos opcionales omitidas. Cinco casos nuevos verifican: correo/adjunto y liga correctos sin duplicados ni aceptación implícita; aprobación sustituida; fallo al generar el PDF sin enviar un mensaje incompleto; incertidumbre sin reenvío; correo local identificado como guardado. Se inspeccionó el PDF de ejemplo de una página. Tipos, compilaciones y seis pruebas existentes del chat aprobados.

Navegador en base aislada `maia_capture_mail_ui_1107`, sin worker ni proveedores externos: liga sin sesión → formulario en modo iniciar sesión → acceso con cuenta de prueba → solicitud correcta y foco en el acuerdo, sin aceptar. Evidencia: `/tmp/maia-crm-review/entrada-desde-correo.png`. La base no contiene datos del piloto y sus procesos temporales se detuvieron al terminar. El flujo completo de cuentas y verificación permanece pendiente en su etapa posterior.

Se actualizaron backend, worker y website conservando volúmenes, y se aplicó `0009` en la instancia activa. Se preparó una sola vez el aviso pendiente de la captación aprobada previamente; el worker lo procesó como `stored` y se comprobó que el mensaje local contiene un adjunto PDF válido. El backend de correo activo es local; no acredita entrega a la bandeja del cliente.

### Validación inicial anterior al correo de aprobación

- Suite completa: 208 pruebas aprobadas y dos opcionales omitidas. Incluye 17 pruebas de captación: autorización por cuenta, CSRF, revisión, aceptación idempotente, seis meses, privacidad, vencimiento, renovación, retirada, imágenes grandes y HEIC, carga deduplicada, entrega incierta, monedas y equivalencias de tipos.
- Seis pruebas existentes del ciclo del chat aprobadas.
- Ruff, comprobación Django, tipos y compilación de producción comprobados. `makemigrations --check --dry-run` sin cambios pendientes tras la migración nueva.
- Proxy real: creación y lectura de conversación con sesión y CSRF aprobadas.
- Recorrido HTTP por el website aprobado: login de propietario, borrador, cinco imágenes optimizadas, giro, orden, envío, revisión staff, aceptación dummy, publicación de Preventa, privacidad y retirada. Los archivos dejaron de ser públicos al retirar la propiedad.
- Navegador de escritorio: opción Preventa y catálogo, mapa, captura de datos, inicio de sesión y guardado del borrador conservando lo escrito. Evidencia local: `/tmp/maia-capture-preview/preventa.png`.
- Sin correos, WhatsApp o Telegram reales; las pruebas de correo usaron el backend en memoria. No se ejecutó el modelo real en este incremento.

## Aceptación manual pendiente

### Verificación obligatoria antes de acceder, 15 de noviembre de 2026

Al repetir el registro después de borrar una cuenta de prueba, Guillermo reportó «No encontramos esa solicitud o archivo» al abrir el correo nuevo. El enlace almacenado para la cuenta recreada respondió 200 en una transacción revertida, sin verificar la cuenta real. Un enlace firmado de la cuenta eliminada reprodujo el 404. No se confirmó qué enlace abrió el navegador. Se sustituyó ese error genérico por una indicación de solicitar un nuevo correo desde la cuenta actual, sin permitir que un enlace de la cuenta anterior verifique la nueva. Pasaron 28 pruebas de captación. Pendiente repetir con un correo reenviado y comprobar el recorrido en el navegador de Guillermo.

Guillermo cambió el criterio: verificar email deja de ser un requisito solo para enviar la captación y pasa a ser requisito de acceso a Mis propiedades y al formulario con sesión iniciada. La cuenta pendiente muestra una tarjeta con ícono de correo, dirección de destino, reenvío, comprobación de verificación y opción de usar otra cuenta. El borrador local se conserva. No se añadieron códigos ni verificación SMS.

La API rechaza con 403 listar, consultar, guardar o modificar captaciones y subir/borrar archivos desde cuentas sin verificar. Los archivos privados y contratos no se entregan a esas cuentas. El estado de cuenta, la verificación y el reenvío siguen disponibles para completar el acceso; el contenido público publicado conserva sus permisos. Tras verificar se cargan las solicitudes y se retoma la acción pendiente. Pasaron 41 pruebas de captación y correo, incluidos registro → bloqueo → verificación → acceso, protección de archivos y reenvío desde cuenta pendiente. Compilación y Ruff aprobados. Falta repetir el recorrido con la cuenta real recién creada por Guillermo.

### Entrada visible a cuentas, 15 de noviembre de 2026

Se añadieron «Crear cuenta» e «Iniciar sesión» a la navegación pública y a la entrada de Propietarios sin sesión. Cada enlace abre directamente el modo correspondiente, sin empezar a capturar una propiedad. Se conservan los borradores de la sesión y el acceso por liga de solicitud. Comprobado en navegador sin sesión: inicio → Crear cuenta → formulario de registro e Iniciar sesión → formulario de acceso. A 390 px no hay desbordamiento horizontal. Compilación aprobada y website actualizado. Esta comprobación no creó cuentas ni acredita entrega o verificación de correos de registro; la prueba 4 sigue pendiente.

### Contacto directo del asesor, 15 de noviembre de 2026

Por solicitud de Guillermo, se eliminó de Mis propiedades el formulario «Habla con tu asesor», incluidas sus opciones de cambio, retirada y renovación. En su lugar aparece el nombre del asesor asignado y su WhatsApp como enlace directo. El número se administra en CRM → Asesores; no se reutiliza el identificador privado de Telegram. La migración `0011_advisor_whatsapp` añade el campo opcional y conserva los asesores existentes. Las pruebas manuales descritas abajo que usan ese formulario quedan sustituidas por esta decisión de producto; los registros históricos se conservan.

Comprobado en la solicitud del piloto con Guillermo Gomez y el número dummy autorizado: el formulario ya no aparece y el contacto corresponde al asesor asignado. Pasaron 56 pruebas de captación y prospectos, incluyendo persistencia/validación del WhatsApp, lectura por el propietario y rechazo de otra cuenta. Tipos, Ruff, compilación y comprobación de migraciones aprobados. Backend, worker y web actualizados. No se aceptó exclusividad ni publicó la propiedad.

### Corrección del CRM y auditoría de almacenamiento, 7 de noviembre de 2026

Guillermo volvió a reportar la pantalla como congelada desde la zona inferior del formulario. Se comprobó que «Actividad y avisos» respondía; la orientación anterior quedaba fuera de la vista y el resultado seguía presentado como botón deshabilitado. Se sustituyó la revisión aprobada por un estado junto a las acciones: explica la espera del propietario, el estado local del correo y permite comprobar aceptación. Ya no muestra las casillas ni los botones de publicar/renovar mientras espera aceptación. El resultado recibe foco al aprobar o abrir la solicitud y la consulta muestra su hora en el mismo lugar. Se probó en la instancia activa: el botón respondió y mostró que sigue pendiente de aceptación. No se modificó ni publicó la captación. Evidencia: `/tmp/maia-crm-review/revision-responde.png`. Tipos y compilación aprobados.

Guillermo reportó que «Aprobar y solicitar aceptación» parecía congelarse y aclaró que no sabía cómo continuar. Se confirmó `approved`, una propiedad no publicada y ningún acuerdo aceptado: la aprobación sí había terminado. La causa fue falta de orientación en pantalla, no un bloqueo reproducido. Se añadió una indicación persistente: el propietario acepta desde su cuenta en Mis propiedades; el equipo actualiza el CRM y publica después. El botón aprobado cambia de texto y durante una escritura aparece «Guardando cambios…». No se repitió la aprobación ni se aceptó el acuerdo del propietario para comprobar esta corrección.

Se verificaron el aviso persistente y el botón «Revisión aprobada» en el CRM activo después de actualizar el website. Tipos, compilación, seis pruebas existentes y proxy aprobados. Evidencia local: `/tmp/maia-crm-review/aprobacion.png`.

El CRM permite ampliar fotos y planos de imagen, navegar con botones o flechas, cerrar con Escape y abrir la imagen en otra pestaña. Se comprobó en la sesión existente de `localhost:3000/crm`: carga de imagen, cambio con flecha derecha, botón Siguiente y cierre con Escape devolviendo foco a la miniatura. Se añadieron explicaciones a las tres casillas de revisión. La captación siguió en revisión; no se aprobaron permisos ni se publicó el inmueble.

Se reconstruyó y actualizó el website activo. Tipos, compilación de producción, seis pruebas existentes del chat y proxy real aprobados. No hubo cambios de backend ni de esquema en esta corrección. Evidencia local del visor: `/tmp/maia-crm-review/foto-ampliada.png`. Falta repetir el visor en un dispositivo móvil y la aceptación de Guillermo.

La auditoría encontró cinco archivos WebP presentes y ninguna referencia perdida en la captación revisada. El [diseño implementado](../architecture/captacion/README.md) registra relaciones, permisos, volumen persistente y pendientes: respaldo externo, restauración conjunta y reconciliación de archivos. No se considera preparado para producción por el solo hecho de que exista un volumen.

### Confirmación y pendientes de producto, 7 de noviembre de 2026

Guillermo confirmó que pudo continuar después de usar el correo de verificación local. No se interpreta esa confirmación como aprobación de todas las casillas siguientes ni como entrega real de email.

- Ajustes visuales pendientes en la captación. Todavía no hay una lista detallada ni aceptación del diseño.
- Rediseñar la manera y el momento en que se pide crear cuenta: la versión actual resulta poco amigable. Conservar datos, fotos y contexto durante el acceso.
- Posponer a otra etapa el flujo completo de cuentas y verificación real de celular y email, con recuperación y errores. Ver [trabajo posterior de cuentas](../design/cuentas-y-verificacion.md).

Continuar la validación funcional de captación; estos pendientes no autorizan omitir controles actuales ni declaran terminado el incremento.

- [ ] Configurar correo real y comprobar registro, verificación, reenvío, login y recuperación. Conservar los datos al crear cuenta desde Guardar o subir fotos.
- [ ] Completar Venta, Renta y Preventa, sin Temporada ni Departamento Compartido. Comprobar subtipos y campos pertinentes para vivienda, inmuebles comerciales, industriales y rurales.
- [ ] Guardar y retomar borradores desde la cuenta. Otro propietario no puede verlos ni consultar sus archivos.
- [ ] Subir fotos desde iPhone y Android, incluidas HEIC y fotos grandes. Comprobar calidad, orientación, portada, orden, giro y reintentos sin duplicados. Enviar con menos de cinco debe fallar; planos, videos y 360 son opcionales.
- [ ] Revisar y aprobar un inmueble fuera de Guadalajara; comprobar datos privados y ubicación pública aproximada. Probar autorización explícita de ubicación exacta.
- [ ] Aceptar el dummy y publicar desde CRM. Repetir clics sin duplicar propiedad ni contrato. Comprobar fotos, planos, enlaces y nuevos detalles en la ficha pública.
- [ ] Buscar en MXN y USD con presupuesto; comprobar etiquetas y ausencia de conversiones. Buscar categorías equivalentes y Preventa.
- [ ] Corregir desde Captación una solicitud enviada. Revisión y aceptación vuelven a ser necesarias; el editor antiguo del inventario dirige a Captación.
- [ ] Registrar opinión de valor y marcarla como comunicada. La opinión no comunicada permanece privada del equipo.
- [ ] Solicitar retirada y renovación desde la cuenta; resolver desde CRM. Probar vencimiento con un caso aislado y fechas controladas. No cancelar citas por despublicar.
- [ ] Comprobar aviso Telegram del responsable y reintento de fallo conocido. No reenviar resultados inciertos.
- [ ] Repetir en móvil, tablet y teclado físico. La revisión visual realizada fue de escritorio.

Registrar ID, fecha, canal o dispositivo, resultado y evidencia. No guardar credenciales ni enlaces privados de verificación en capturas compartidas.
