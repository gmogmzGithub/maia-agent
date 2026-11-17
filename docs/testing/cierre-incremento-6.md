# Guía de cierre del incremento 6

## Cierre de aceptación para BETA · 16 de noviembre de 2026

Guillermo aceptó las 12 pruebas del [recorrido manual vigente](sexto-incremento-recorrido-manual.md). El incremento 6 queda cerrado para BETA por aceptación del usuario. Los casos detallados de esta guía conservan su evidencia y estado histórico; no se atribuyen nuevas ejecuciones técnicas individuales por esta confirmación. El contrato definitivo, cuentas/SMS y preparación para producción continúan separados.

## Guía original y evidencia histórica

Preparada el 15 de noviembre de 2026. Registro de ejecución: cada caso empieza pendiente salvo evidencia explícita. No marcar el conjunto aprobado por haber recibido un correo.

## Estado inicial

- Resend activado en backend y worker; comprobación de configuración sin incidencias y webhook configurado. La web pública respondió HTTP 200 y el webhook HTTP 405 a GET, coherente con una ruta que recibe POST; esto no acredita un evento firmado recibido.
- Guillermo confirmó que funciona el envío real de aprobación. Falta registrar por separado PDF, destino de la liga y evento `delivered`.
- La suite histórica reportó 230 pruebas aprobadas y dos opcionales omitidas. No se volvió a ejecutar al preparar esta guía.
- No están confirmadas aquí la aceptación del propietario ni la publicación de su captación.
- El contrato sigue siendo dummy. El flujo completo de cuentas y la verificación de posesión del celular quedan en la etapa posterior. Sí se valida el registro, correo y recuperación ya implementados.

## Preparación

1. Usar únicamente propiedades de prueba, títulos `PRUEBA I6`, datos ficticios y correos y teléfonos controlados por Guillermo. Las pruebas envían avisos reales.
2. Mantener una ventana para el equipo CRM, otra sesión para el propietario A y un perfil separado para el propietario B. Dos pestañas de incógnito del mismo perfil suelen compartir sesión: usar otro perfil o navegador para B. Una ventana sin sesión sirve como visitante.
3. Entrar por `https://sandbox.elmenlabs.com/propietarios` y `/crm`. Usar el mismo dominio durante el recorrido de correo; localhost tiene otra sesión. Mantener Docker y el túnel en ejecución.
4. Preparar al menos seis fotos propias, una HEIC, una foto grande de celular, una vertical, un plano PDF y otro en imagen. Tener un enlace válido de video y otro 360. Planos y enlaces son opcionales.
5. Crear los casos A: Venta, casa de Guadalajara, MXN; B: Renta, departamento de Zapopan, USD; C: Preventa, propiedad fuera de la zona base, MXN. Pueden usarse esas mismas solicitudes en las pruebas posteriores.
6. Registrar por caso ID de solicitud y propiedad, navegador/dispositivo, resultado, fecha y evidencia sin claves, enlaces de acceso ni datos personales.

## T01. Cuenta, verificación y recuperación actuales

1. Sin sesión, comenzar A y escribir datos antes de guardar o subir fotos. Al pedir cuenta, crear propietario A con email, teléfono y contraseña.
2. Comprobar conservación de lo escrito al entrar, salir del panel de cuenta y volver. Usar «Ya tengo cuenta» y comprobar que abre inicio de sesión.
3. Intentar enviar antes de verificar email o completar teléfono. Debe explicar lo que falta y conservar la solicitud.
4. Pedir reenvío de verificación, recibir el correo real y abrir el enlace más reciente. Volver a la solicitud, confirmar el teléfono y continuar. No se espera SMS.
5. Cerrar sesión, entrar con contraseña y comprobar borrador. Probar contraseña incorrecta: debe rechazar acceso sin perder el contexto.
6. Pedir recuperación, recibir el correo real, cambiar contraseña y entrar con la nueva. La anterior debe fallar. Reutilizar el enlace de recuperación debe fallar.
7. Crear B como segunda cuenta para las pruebas de autorización. Un email ya registrado no debe crear otra cuenta ni sobrescribir la anterior.

Esperado: acceso privado, correo real, mensajes claros y recuperación del trámite. El diseño completo de cuentas sigue diferido; cualquier bloqueo del recorrido actual es un fallo del incremento.

## T02. Operaciones, catálogo y validaciones

1. Completar los datos de A, B y C. Preventa debe conservarse como condición de Venta, sin convertirse en Renta.
2. Antes de enviar, recorrer los 19 tipos del selector: Departamento, Bodega comercial, Casa, Casa en condominio, Casa con uso de suelo, Dúplex, Edificio, Huerta, Inmueble productivo urbano, Local Comercial, Local en centro comercial, Nave industrial, Oficina, Quinta, Rancho, Terreno / Lote, Terreno comercial, Terreno industrial y Villa.
3. Revisar los seis subtipos de Departamento, cinco de Casa, dos de Edificio y seis de Terreno / Lote contra las capturas de referencia. Los demás no deben exigir subtipos. Cambiar de tipo no debe dejar un subtipo incompatible.
4. Guardar y recargar un borrador de vivienda, uno comercial, uno industrial y uno rural, usando los campos pertinentes de cada uno. No es necesario publicar 19 propiedades para revisar el selector.
5. Revisar conservación: Excelente, Bueno, Regular, Malo, Remodelado y Para remodelar. Revisar grupos de comodidades y conservar selección tras recargar.
6. Probar campos obligatorios vacíos, precio y superficies inválidos. Deben aparecer errores concretos, sin perder otros datos. Corregir y continuar.

Esperado: sin Temporada, Departamento Compartido ni cobro de publicación. Solo Venta, Renta y Preventa acordadas, tipos válidos y datos conservados.

## T03. Borradores y concurrencia

1. Guardar A incompleta con «Guardar y salir». Recargar, cerrar sesión y volver a entrar en «Mis propiedades».
2. Retomar y comprobar operación, datos, ubicación, comodidades y fotos ya cargadas. Empezar otra propiedad y comprobar que no abre A por una liga anterior.
3. Abrir un borrador en dos pestañas. Guardar un cambio en una y después intentar guardar desde la otra con la versión anterior.

Esperado: borrador recuperable; una versión antigua no sobrescribe silenciosamente la nueva y se indica cómo actualizar.

## T04. Fotos, planos y enlaces

1. Subir fotos grandes y HEIC sin comprimir manualmente, desde iPhone y Android cuando estén disponibles. Confirmar vista previa, orientación y calidad.
2. Cambiar portada y orden, girar una imagen, eliminar una y volver a cargar. Guardar y recargar: los cambios persisten.
3. Cortar brevemente la conexión durante una carga y restaurarla. Reintentar el archivo fallido: no debe duplicarse ni perder los demás.
4. Intentar enviar con cuatro fotos: debe bloquearse. Añadir la quinta: debe permitir continuar con los demás requisitos satisfechos.
5. En A dejar planos, video y 360 vacíos; debe poder enviarse. En B cargar planos PDF e imagen y enlaces de video/360. Comprobar apertura de cada recurso.
6. Probar un archivo que no sea imagen ni plano admitido: error comprensible, sin romper el resto de cargas.

Esperado: cinco fotos mínimas, recursos adicionales opcionales, sin pedir al cliente reducir fotos comunes. La compresión, metadatos y límites de seguridad se verifican también técnicamente en T17.

## T05. Envío y revisión CRM

1. Revisar la vista previa y enviar A. Intentar un segundo clic y recargar.
2. Entrar al CRM, localizar A, comparar datos/fotos/planos y asignar responsable.
3. Ampliar fotos, navegar anterior/siguiente, usar flechas y Escape. Abrir y cerrar desde móvil. El foco debe volver a la miniatura.
4. Intentar aprobar sin verificar al propietario o representante: debe impedirlo. Después marcar esa verificación en el caso de prueba.
5. Aprobar A. Debe mostrar claramente la espera de aceptación y permitir seguir usando la página. No debe publicarse todavía.
6. Comprobar aviso al responsable por Telegram si está configurado para este piloto. Si no lo está, registrar el bloqueo; no darlo por probado.

Esperado: una solicitud, revisión humana obligatoria, responsable correcto y orientación clara tras aprobar.

## T06. Correo, PDF y liga

1. Recibir el aviso de A. Para un aviso previamente guardado localmente, usar una vez «Enviar correo con el proveedor configurado».
2. Abrir PDF: comprobar que corresponde a A, indica dummy, exclusividad de seis meses y ausencia de cobro por publicar.
3. Abrir la liga sin sesión: debe pedir acceso y después mostrar A y su acuerdo. Repetir con sesión correcta ya abierta.
4. Abrir esa liga con propietario B: debe negar acceso al contenido de A.
5. En CRM «Actividad y avisos» comprobar `delivered`; contrastar el evento del mismo correo en Resend. `sent` solo confirma aceptación por el proveedor.
6. Recargar o repetir la acción si sigue visible: no debe crear otro envío conocido ni otro contrato. Fallos ambiguos no se fuerzan a reenviar.

Esperado: destinatario y solicitud correctos, PDF privado y confirmación firmada registrada. Si Resend muestra entrega pero Maia no, registrar fallo del webhook.

## T07. Aceptación y publicación

1. Como A, revisar el contrato y probar aceptar sin marcar consentimiento: debe impedirlo. Marcar y aceptar.
2. Recargar: comprobar aceptación y fechas de seis meses desde aceptar, sin renovación automática. Descargar la copia aceptada.
3. Volver al CRM y usar «Comprobar aceptación del propietario». Ahora debe habilitar la publicación para el equipo.
4. Pulsar «Publicar inmueble», repetir clic/recargar y abrir «Ver publicación» y el catálogo como visitante.
5. Comparar operación, Preventa cuando aplique, moneda, importe, datos, comodidades, portada, orden, fotos, planos y enlaces. No debe aparecer más de una propiedad por solicitud.

Esperado: aprobar no equivale a aceptar ni publicar; aceptar no publica automáticamente; el equipo publica una sola vez.

## T08. Zona y ubicación privada

1. En C, fuera de Guadalajara y su zona metropolitana, intentar aprobar sin permiso de captación fuera de zona: debe impedirlo. Autorizar como equipo y completar aceptación/publicación.
2. En una publicación sin permiso de ubicación exacta, abrir como visitante y comprobar dirección oculta y mapa aproximado cuando existan coordenadas.
3. En otra solicitud de prueba autorizar ubicación exacta, completar el flujo y comprobar el resultado público.
4. Revisar ficha pública, chat y archivos: no deben mostrar teléfono/email del propietario, notas privadas o contrato. Comprobar técnicamente respuestas de API en T17.

Esperado: fuera de zona requiere aprobación expresa; los datos exactos solo se publican con permiso.

## T09. Aislamiento por cuenta y por estado

1. Copiar las rutas privadas de solicitud, foto, plano y contrato de A, sin compartirlas fuera de la prueba.
2. Abrirlas sin sesión y con B antes de publicar: no deben devolver contenido. B tampoco ve A en «Mis propiedades» ni accede al CRM.
3. Publicada A, sus recursos públicos previstos pueden verse, pero el contrato y los datos privados siguen protegidos.
4. Tras retirar A en T13, repetir la ficha pública y las URLs públicas de sus archivos: ya no deben servir el inmueble retirado. El propietario y equipo conservan acceso privado autorizado.

Esperado: ningún acceso cruzado ni archivo privado accesible por conocer su URL.

## T10. Monedas, búsquedas y regresión

1. Publicar las propiedades de prueba MXN y USD necesarias. Buscar con presupuesto explícito en MXN y después USD, usando importes que permitan distinguir ambas.
2. Confirmar exclusión de la otra moneda en una búsqueda con presupuesto; no convertir importes silenciosamente. Sin presupuesto, ambas monedas pueden aparecer etiquetadas.
3. Buscar casa, departamento, comercial, industrial, rural y Preventa, usando los casos publicados pertinentes. Probar equivalencias de tipo y subtipo.
4. Abrir propiedades existentes anteriores al incremento y comprobar que continúan visibles con sus datos y fotos. En el chat, abrir una propiedad y usar «Me interesa».

Esperado: filtros correctos y sin regresión del inventario y chat existentes. La respuesta del modelo real se registra aparte de las pruebas de filtros deterministas.

## T11. Corrección después de aceptar/publicar

1. En una propiedad de prueba publicada, como propietario solicitar un cambio con mensaje; comprobarlo en CRM.
2. Desde Captación usar «Corregir información», cambiar precio o descripción y guardar.
3. Comprobar despublicación inmediata y necesidad de nueva revisión/aceptación. El acuerdo viejo no autoriza publicar el cambio.
4. Abrir la liga anterior: no debe permitir aceptar una versión sustituida. Reaprobar, recibir el contrato actualizado, aceptar y publicar otra vez.
5. Intentar editar esa propiedad desde el editor antiguo del inventario: debe dirigir a Captación, sin omitir controles.

Esperado: historial conservado, nueva aceptación para nueva revisión y sin duplicar inventario.

## T12. Opinión de valor

1. Solicitar opinión de valor en un caso. En CRM registrar importe y comentarios sin marcar «Ya la comuniqué al propietario».
2. Como propietario y visitante, comprobar que no se ve esa opinión privada.
3. Registrar la opinión como comunicada y comprobar que A puede verla con la moneda correcta. B y el visitante no deben acceder.

Esperado: visible al propietario solo al comunicarla; nunca sustituye automáticamente el precio publicado.

## T13. Retirada, renovación y descarte

1. En un caso publicado, solicitar renovación desde «Habla con tu asesor», añadir mensaje y enviarlo. Confirmar recepción en CRM.
2. Usar «Preparar renovación». Comprobar nuevo aviso/PDF, nueva aceptación requerida y fechas resultantes. Registrar explícitamente cómo queda la publicación mientras espera; no asumir prórroga automática.
3. Aceptar la renovación y verificar su registro e historial. No deben duplicarse propiedad ni acuerdo por clic repetido.
4. Solicitar retirada desde la cuenta y resolver desde CRM con «Retirar y cancelar exclusividad». Confirmar desaparición pública y privacidad de archivos conforme a T09.
5. Preparar en un caso aislado una cita pendiente antes de retirar. Confirmar que sigue registrada después, sin cancelación automática.
6. En otra solicitud prescindible usar «Descartar solicitud»: no debe publicarse ni afectar las demás.

Esperado: solicitudes visibles y resolubles, renovación explícita y retirada con historial conservado.

## T14. Vencimiento controlado, comprobación técnica

1. Usar una base aislada y fechas controladas; no modificar reloj ni fechas del piloto.
2. Vencer el acuerdo de una propiedad publicada y comprobar que inventario, detalle público y recursos dejan de exponerla incluso antes del siguiente mantenimiento.
3. Ejecutar el mantenimiento y comprobar estado final, historial y citas conservados. Repetir ejecución sin duplicados.

Esperado: sin publicación fuera de vigencia. No hace falta esperar seis meses ni alterar contratos reales.

## T15. Móvil, tablet y teclado

1. En iPhone y Android repetir registro/acceso, carga de fotos, guardado, liga de correo y acuerdo. Si falta un dispositivo, marcarlo pendiente.
2. En tablet y escritorio revisar formulario, visor, CRM y ficha pública. Probar teclado móvil abierto, orientación y textos largos.
3. Con Tab/Shift+Tab/Enter/Escape recorrer campos, errores, diálogos y acciones. Comprobar foco visible, retorno tras cerrar y ausencia de superposición o desplazamiento horizontal involuntario.

Esperado: completar las acciones sin controles ocultos, pérdida de datos ni bloqueos. Registrar ajustes visuales concretos; separar preferencia estética de impedimento funcional.

## T16. Durabilidad y restauración

1. Guardar ID de un borrador con archivos, una publicación y un acuerdo aceptado. Realizar respaldo consistente de PostgreSQL y archivos privados de captación, con acceso restringido.
2. Restaurar el conjunto en un entorno aislado, con worker y proveedores externos desactivados. Comprobar relaciones, imágenes, permisos y PDF aceptado. No restaurar sobre el piloto.
3. Reiniciar los servicios del piloto conservando volúmenes y comprobar los tres registros y sus archivos. No eliminar volúmenes.
4. Conservar una copia externa protegida y registrar ubicación operativa, fecha y resultado de restauración, sin secretos.

Esperado: persistencia entre reinicios y restauración comprobada. Un volumen por sí solo no acredita respaldo.

## T17. Comprobaciones técnicas de cierre

Responsabilidad técnica: ejecutar en entorno de prueba y registrar salida, versión y fecha. No pedir a Guillermo falsificar firmas, forzar reintentos inciertos ni manipular la base activa.

1. Suite backend y pruebas existentes del frontend; revisión estática, tipos y compilación de producción. Revisar explícitamente los dos casos opcionales omitidos: motivo y relevancia para el cierre.
2. Django y migraciones sin cambios inesperados; proxy real con `backend/scripts/check_web_routes.py` contra la plataforma en ejecución.
3. Autorización/CSRF, revisión obsoleta, aceptación y publicación idempotentes; no filtrar dirección, contacto, contrato ni notas en respuestas públicas.
4. Imágenes reducidas y orientadas, sin EXIF/XMP del original; giro mantiene compresión. Carga HEIC, protección por tamaño/píxeles, deduplicación y rutas privadas. No prometer tamaños ilimitados ni un máximo de KB que el compresor trate como objetivo.
5. Webhook: firma alterada, fecha inválida y evento duplicado rechazados o deduplicados; eventos desordenados no degradan `delivered`. Validar correspondencia real entre evento de Resend y CRM sin exponer secretos.
6. Proveedor: rechazo conocido permite reintento autorizado; timeout/resultado ambiguo no duplica correos; rebote/queja/supresión no reactivan reenvío. Telegram cubre fallo conocido e incertidumbre con transporte simulado, además del aviso real de T05 cuando aplique.
7. Auditoría de almacenamiento de solo lectura: `check_capture_storage --verify-images --find-orphans`. Investigar cada referencia perdida o huérfano, sin borrar automáticamente.
8. Renovación, vencimiento, privacidad tras retirada e inventario anterior cubiertos por pruebas. Ejecutar T14 y T16 con aislamiento.

## Registro y criterio de cierre

| Caso | Estado | ID / dispositivo | Evidencia o fallo |
| --- | --- | --- | --- |
| T01–T17, registrar una fila por caso al ejecutar | Pendiente | | |

Estados: aprobado, fallido, bloqueado o pendiente. Un caso parcialmente ejecutado sigue pendiente; dividirlo en subcasos cuando haga falta. Cada fallo debe incluir pasos, resultado esperado y observado, y evidencia. Repetir el caso afectado después de corregirlo.

Cerrar el incremento cuando los recorridos y controles del alcance pasen, no queden fallos de datos/permisos/contratos/publicación/entrega y Guillermo acepte el resultado. Cualquier excepción necesita quedar explícita con alcance y responsable; no marcarla como prueba aprobada. Mantener separados los pendientes de Meta del incremento 4, el incremento 5 pospuesto, el rediseño completo de cuentas/SMS y el contrato definitivo.
