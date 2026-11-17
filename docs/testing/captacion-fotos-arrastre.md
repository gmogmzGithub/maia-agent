# Captación: arrastre y cola de fotos

Implementado el 15 de noviembre de 2026 dentro del incremento 6. Mínimo cinco y máximo veinte fotos; hasta cinco planos opcionales. No cambia almacenamiento, publicación, permisos ni contrato de exclusividad.

## Estructura

- `frontend/src/main-website/components/CaptureMedia.tsx`: zonas separadas para fotos y planos; selector accesible, arrastre externo, arrastre interno con MIME propio y botones alternativos para orden/portada/giro/eliminación. Los archivos rechazados se identifican por nombre y motivo. Evita abrir un archivo en el navegador si se suelta fuera de una zona durante este paso.
- `frontend/src/main-website/lib/capture-upload-queue.ts`: cola secuencial por cuenta y borrador. Reserva cupos para pendientes y fallidos, admite incorporaciones durante una carga y libera el `File` al confirmarla. Estados: `queued → preparing → uploading → uploaded`, con `failed → queued` al reintentar. Las tarjetas pendientes muestran nombre y estado; la miniatura normalizada aparece al confirmar el servidor, evitando decodificar todos los originales grandes simultáneamente.
- `frontend/src/main-website/hooks/useCaptureUploads.ts`: suscripción React, persistencia inicial del borrador, reconciliación con el servidor y advertencias de salida. Una cuenta creada/verificada durante el acceso continúa en la cola vigente, sin reutilizar una cola de la cuenta anterior.
- `frontend/src/shared/lib/capture.ts`: conserva optimización a WebP y transporte `multipart/form-data`, con aviso del comienzo del envío. HEIC no decodificable por el navegador conserva la ruta de normalización del backend.
- `backend/datalayer/capture_catalog.py`: fuente de límites publicados mediante catálogo. `capture_assets.py` impone el máximo bajo bloqueo; `captures.py` impone 5–20 al enviar. No se borran automáticamente fotos anteriores al cambio de límite.

`CaptureAsset` conserva su estructura. Se devuelve `request_id`, ya único por captura, para reconciliar una respuesta perdida antes de reintentar. La URL privada añade una versión opaca derivada del nombre interno: al girar cambia la URL y el navegador refresca la imagen sin revelar el nombre de almacenamiento. No se añadieron tablas ni migraciones. El backend mantiene validación de archivos, orientación, reducción, eliminación de EXIF y permisos existentes.

La cola solo vive en memoria. No se serializan `File` ni miniaturas temporales. Recargar/cerrar pierde pendientes; las fotos confirmadas siguen en el servidor. Al restaurar el borrador se concilian los archivos con una lectura autorizada, conservando los campos editados y la revisión local para no ocultar conflictos de escritura. Reintentar conserva `request_id`; no hay detección de dos incorporaciones independientes del mismo contenido.

Agregar archivos sigue disponible durante una carga. Reordenar, girar, eliminar archivos guardados y las acciones de navegación del formulario esperan a que termine. Los fallos individuales se reintentan o quitan de la cola antes de continuar. Guardar/salir o cerrar sesión con fallidos exige confirmar que se descartan pendientes. El navegador puede limitar las advertencias de cierre en dispositivos móviles; no se promete reanudación.

## Comprobación realizada

- Frontend: 19 pruebas aprobadas, incluidas seis de cola y siete de recuperación/autorización de borrador. Cubren adición durante una carga, cupos con pendientes/fallidos, fallo parcial, reintento con el mismo ID, respuesta perdida con reconciliación inmediata o posterior y descarte de tareas al desmontar.
- Backend: suite completa inicial de 250 aprobadas y dos opcionales omitidas; después 30 casos de captación aprobados tras añadir la prueba del cambio de URL al girar. El caso de veinte fotos verifica rechazo de una adicional y reintento válido al estar lleno. Ruff, TypeScript, compilaciones y ausencia de migraciones comprobados. Proxy real comprobado.
- Navegador en sandbox, con imágenes sintéticas y borrador técnico independiente: una imagen inválida falló sin impedir dos cargas válidas; reintentar no duplicó las válidas. Orden por arrastre confirmado. Mínimo bloqueó continuar con dos fotos. Con tres guardadas, un lote de 19 añadió 17 e identificó las dos excedentes; se confirmaron veinte archivos en pantalla y base de datos. Giro comprobado con cambio de URL y dimensiones naturales. Se comprobó la restauración al recargar y vista de 390 px sin desbordamiento horizontal.
- La aceptación manual de la prueba 6 sigue pendiente: arrastrar archivos desde el explorador, fotos reales grandes/HEIC en un celular físico, planos/PDF y aviso de salida en los navegadores que se usarán. La prueba automatizada de carga usa el selector nativo de macOS; no acredita arrastre externo entre aplicaciones.

Evidencia local: `/tmp/maia-photo-drop/`. El borrador técnico y sus veinte archivos se eliminaron tras la comprobación, verificando que no quedaran registros ni archivos de ese caso; no se publica ningún inmueble ni se envían correos durante esta prueba.
