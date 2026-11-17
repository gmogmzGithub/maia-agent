# Captación: diseño implementado y almacenamiento

Revisión inicial del 7 de noviembre de 2026, ampliada el 15 de noviembre con [Google Places/Maps](../../testing/google-ubicacion-beta.md). Describe el incremento 6 implementado. Complementa el [plan funcional](../../design/plan-sexto-incremento.md) y la [organización del código](../code-structure.md).

[Abrir el diagrama interactivo](actual.html). Representa el diseño inicial del 7 de noviembre, anterior a Google; la ampliación actual se describe en la sección siguiente.

## Ubicación Google, 15 de noviembre de 2026

`GoogleLocation` guarda identificador y punto temporales, con propietario/fuente/vigencia. `GoogleSearchSession` agrupa consultas por propietario; `GoogleLocationUsage` reserva consumo por mes/SKU bajo bloqueo. La migración `0012` añade estos registros sin modificar identificadores ni datos históricos de captación.

La dirección declarada y los datos comerciales siguen en `Capture.data`. Una ubicación Google se vincula mediante una referencia privada; no se copian sus coordenadas a ese JSON. La API entrega el punto autorizado por separado, sin caché HTTP, y el borrador del navegador omite ese resultado técnico. Contratos/adjuntos excluyen la referencia; el refresco no cambia la revisión comercial ni invalida avisos aprobados.

Para Google, `Property.public_location` contiene únicamente un indicador de consulta. La ficha obtiene por una ruta pública el punto exacto solo si fue autorizado; en otro caso obtiene una zona resuelta independientemente, sin revelar el identificador o punto privados. Las conversaciones pueden conservar el indicador público, pero no las coordenadas Google. Los puntos históricos aportados independientemente conservan su comportamiento previo.

Vigencia: 29 días. El mantenimiento horario borra valores vencidos y renueva los automáticos activos próximos a vencer. Un ajuste manual del mapa no se sustituye por Google: vencido requiere reconfirmación. Los respaldos/exportaciones deben excluir valores temporales o respetar su vigencia; un TTL lógico no limpia una copia externa por sí mismo. La [guía operativa](../../testing/google-ubicacion-beta.md) documenta estos límites, el corte local de solicitudes y la configuración pendiente.

## Datos persistentes

| Registro | Qué conserva |
| --- | --- |
| `User` | Cuenta, teléfono y fecha de verificación de email. El teléfono todavía no tiene verificación SMS. |
| `Capture` | Propietario, asesor, estado, revisión, datos del formulario, responsable y fecha de revisión, permisos geográficos y notas privadas. |
| `CaptureAsset` | Captación, archivo, tipo, tamaño, orden y clave de reintento. La base guarda la referencia al archivo, no los bytes de la foto. |
| `CaptureAgreement` | Texto y versión del dummy, copia de los datos aceptados, usuario, aceptación, vencimiento y terminación. |
| `CaptureEvent` | Actor, acción y fecha del historial. No constituye una copia completa de cada versión del formulario. |
| `CaptureDelivery` | Destinatario, contenido y estado de los avisos; evita duplicar un evento. El campo `attachment` conserva los datos y el texto/versionado de la copia de contrato enviada al propietario. |
| `CaptureMailEvent` | Identificador, tipo y fecha de las confirmaciones firmadas de Resend. No guarda cuerpo, dirección del destinatario ni tokens. |
| `Property` | Proyección del inmueble aprobado para inventario y publicación. Una captación tiene como máximo una propiedad asociada. |

Los datos editables de `Capture.data` usan JSON validado por `CaptureData`. Esto permite guardar borradores incompletos; el envío y la aprobación exigen campos completos. La validación de esos campos ocurre en la aplicación, no mediante columnas y restricciones individuales de PostgreSQL. Los vínculos de cuenta, asesor, propiedad, archivos y acuerdos sí son relaciones de base de datos.

Las mutaciones usan transacciones, bloqueo de la captación y control de revisión. La clave única de carga impide duplicar una foto al reintentar la misma solicitud. Los modelos nuevos conservan el identificador Django `core` y sus tablas históricas.

## Recorrido de una imagen

1. El navegador intenta reducir la foto antes de subirla. El servidor vuelve a validar y normalizar, independientemente del navegador.
2. El backend decodifica el archivo, corrige orientación, limita el lado mayor a 2400 píxeles, elimina EXIF/XMP y genera WebP. Busca un peso de 800 KB ajustando calidad y dimensiones; no debe interpretarse como una garantía absoluta para cualquier contenido.
3. Se guarda únicamente la versión normalizada con nombre aleatorio. El original no se conserva. HEIC se decodifica en el backend; se aplican límites de protección de 256 MiB por carga y 100 megapíxeles.
4. `CaptureAsset` registra la ruta relativa y metadatos. En Docker los bytes viven en el volumen persistente `capture_media`, montado como `/app/media` en backend y worker. Fuera de Docker se usa `CAPTURE_MEDIA_ROOT` o `backend/media`.
5. La lectura pasa por `/api/capture/assets/<uuid>`. Antes de publicar, solo el propietario autenticado y el equipo pueden leer. Después de publicar, el acceso público exige propiedad publicada y acuerdo vigente. Retirar o vencer la exclusividad bloquea la lectura pública.

El identificador del archivo no concede acceso por sí mismo. Los archivos no se sirven directamente desde una carpeta pública de Next.js. La respuesta incluye `private, no-store`, `nosniff` y una política restrictiva de contenido.

Los planos son opcionales: imágenes con la misma normalización o PDF sin contraseña, hasta 20 MiB y 50 páginas. Los PDF se descargan y no se incrustan como contenido activo. Comprobar estructura y páginas no equivale a analizar malware ni eliminar todos los metadatos de un PDF. Videos y recorridos 360 se guardan como enlaces, no como archivos alojados.

El CRM muestra miniaturas y permite abrir imágenes completas, recorrerlas con botones o flechas, cerrar con Escape y abrir el archivo en otra pestaña. La autorización sigue siendo la del backend.

## Revisión y publicación

`draft` → `submitted` → `approved` → aceptación del propietario → `published`.

El acuerdo dura seis meses calendario desde la aceptación. La publicación requiere aceptación vigente. Una corrección invalida la aceptación anterior y devuelve el inmueble a revisión. Vencimiento o retirada despublican sin borrar historial ni cancelar citas. Renovar exige nueva aceptación. El worker procesa avisos y vencimientos; el inventario público también comprueba la vigencia al consultar.

### Aviso de aprobación al propietario

La aprobación y la preparación de una renovación crean, en la misma transacción, un correo pendiente con una copia de los datos y del contrato dummy. La clave por captación y revisión evita duplicar esa solicitud de envío. El worker genera el PDF desde esa copia, no desde un formulario que pudo cambiar mientras esperaba. El PDF identifica inmueble, operación, versión y condiciones; se marca como demostración sin aceptar. No es una firma ni inicia los seis meses.

El correo contiene `/propietarios?capture=<uuid>`. La pantalla solicita inicio de sesión si hace falta, conserva el destino y enfoca el acuerdo de esa solicitud. El backend comprueba que pertenezca a la cuenta autenticada; la liga no concede acceso ni acepta el contrato. Las versiones nuevas del contrato deben cambiar `CONTRACT_VERSION`.

Antes de enviar, el worker descarta avisos cuya aprobación o datos ya no coinciden. Una nueva aprobación sustituye los avisos anteriores todavía pendientes. Si falla la generación del PDF no se envía un correo sin contrato. Un resultado de envío incierto no se reintenta automáticamente. El equipo puede reintentar un fallo conocido desde Actividad y avisos.

Con correo local de desarrollo, el estado es `stored`: se guardó el mensaje con el PDF en `private_mail`, pero no se entregó al destinatario. Con SMTP, `sent` significa aceptación por el proveedor, no confirmación de lectura ni garantía de llegada a la bandeja. La entrega real sigue requiriendo configuración y prueba del proveedor.

La integración opcional con Resend envía por HTTPS usando adjuntos Base64, HTML escapado y texto alternativo. `CaptureDelivery` conserva proveedor, identificador externo e intentos. Un webhook verifica firma Svix sobre el cuerpo original, deduplica eventos y distingue aceptación, entrega al servidor del destinatario, demora, rebote y queja. Una confirmación puede llegar antes de la respuesta HTTP y recuperar el resultado sin reenviar. Los estados confirmados no retroceden ante un evento antiguo. Ver [activación y contrato del transporte](../../testing/resend-beta.md). El diagrama conserva la configuración local por defecto; Resend todavía no está activado en el piloto.

El propietario y el equipo pueden descargar el PDF mediante una ruta autenticada. La copia aceptada se genera desde `CaptureAgreement.snapshot`, texto y versión guardados, incluso si después se modifica el formulario. No se concede acceso al contrato por conocer el UUID.

| Casilla del CRM | Regla y efecto persistente |
| --- | --- |
| Verifiqué al propietario o representante y el inmueble | Obligatoria para aprobar. Registra revisor y fecha. Confirma una revisión humana; no consulta documentos ni verifica identidad automáticamente. |
| Apruebo la captación fuera de la zona base | Obligatoria solo fuera de Guadalajara y su zona metropolitana según el catálogo de municipios del backend. Registra la excepción comercial del equipo. |
| Autorizo publicar la ubicación exacta | Opcional y desmarcada por defecto. Marcada permite copiar dirección y coordenadas exactas a la proyección pública. Desmarcada omite dirección exacta y redondea coordenadas a dos decimales cuando existen. |

La tercera casilla registra la decisión del equipo; no obtiene consentimiento del propietario por sí sola. La aproximación por redondeo tampoco garantiza anonimato frente a fotos, descripción o referencias del inmueble. La aprobación y el historial identifican al actor, pero no conservan un comprobante documental de identidad ni un consentimiento específico de ubicación.

## Comprobación de la instancia local

Se contrastaron los cinco registros de foto de la captación revisada con el almacenamiento activo: cinco archivos presentes, todos WebP, tamaños de 45 042 a 265 278 bytes y ninguna referencia sin archivo. La consulta fue de lectura; no se aprobó, publicó ni modificó esa captación.

El diseño es adecuado para el piloto de una instancia. Persistencia de volumen significa que las imágenes sobreviven al reemplazo de contenedores; no garantiza recuperación ante pérdida del equipo o eliminación del volumen.

## Pendientes antes de producción

- Respaldar fuera del equipo PostgreSQL y los archivos, y probar una restauración coordinada. Restaurar solo la base deja referencias sin fotos; restaurar solo el volumen pierde relaciones y acuerdos.
- Definir la durabilidad del almacenamiento en el despliegue elegido. Actualmente no hay almacenamiento de objetos externo ni replicación de imágenes. Si el despliegue usa varias instancias, todas necesitan acceso al mismo almacenamiento duradero.
- Añadir reconciliación de referencias y archivos huérfanos. PostgreSQL y el sistema de archivos no comparten una transacción: las compensaciones actuales reducen fallos, pero una interrupción durante carga o giro puede dejar archivos sin registro. Todavía no hay comprobación periódica de integridad por checksum.

Ya existe una auditoría manual de solo lectura: `check_capture_storage --verify-images --find-orphans` detecta archivos ausentes, tamaños distintos, imágenes no legibles y posibles huérfanos. No elimina ni repara nada y no sustituye un respaldo. El giro de fotos reutiliza la normalización, comprime antes del bloqueo corto y vuelve a aplicar el objetivo de tamaño para web.

No se implementan estos cambios de infraestructura en la corrección del visor. Tampoco se declara completo el flujo de cuentas: sus pendientes permanecen en [cuentas y verificación](../../design/cuentas-y-verificacion.md).

## Fuentes y validación del diagrama

- Modelos y relaciones: `backend/datalayer/models.py`, migración `0008_capture_owner_intake`.
- Entrada, permisos y lectura: `backend/api/capture.py`.
- Validación y ciclo de vida: `backend/datalayer/capture_schemas.py`, `captures.py`, `inventory.py`.
- Procesamiento y persistencia: `backend/datalayer/capture_media.py`, `capture_assets.py`, `capture_contract.py`, `backend/worker/capture_delivery.py`, `backend/maia/settings.py`, `compose.yaml`.
- Interfaz: `frontend/src/main-website/pages/OwnerCapture.tsx`, `frontend/src/crm/components/Captures.tsx`, `CapturePhotos.tsx`.

Entrega determinista: 9/9 comprobaciones showcase, cero errores y advertencias. Evidencia automatizada aprobada en 1440×900, 1600×1000, 1920×1080 y 2048×1320, sin desbordamiento. Se inspeccionaron las imágenes de tema claro a 2048×1320 y oscuro a 1440×900: texto y conexiones sin superposiciones; revisión visual aprobada. Dos correcciones de composición previas a la entrega.

```text
diagram_type: architecture
output: /Users/el-men/Workspace/maia-agent/docs/architecture/captacion/actual.html
specification_sha256: 494627ac689a368cd330cf1c96e0453c9da73f5d4e5b25f9c5469d1aa90afc9a
artifact_sha256: 99ffcba83069f40ea23990c27f3df64424f6a5f14df013b30dee020cb91c3086
validation: 9/9 showcase, 0 errors, 0 warnings
browser_evidence: passed
visual_review: passed
correction_rounds: 2
```

La [evidencia automatizada](actual.visual-check.json) identifica el HTML por hash y conserva la revisión perceptual como pendiente, porque esa herramienta no emite juicios visuales. La revisión de las dos imágenes descrita arriba se registra por separado.
