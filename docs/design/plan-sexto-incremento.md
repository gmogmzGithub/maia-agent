# Implementación del incremento 6

Guillermo confirmó el alcance funcional y añadió Preventa. Se representa como una condición de Venta (`is_presale`), compatible con tipo, conservación y antigüedad, sin introducir Temporada ni una operación de renta preventiva.

## Etapas

1. Datos y contratos: ampliar inventario de forma compatible; conservar MXN y publicación de propiedades previas. Añadir captaciones privadas, archivos, revisión, aceptación versionada y entregas durables.
2. Cuenta y formulario: registro con email, teléfono y contraseña, verificación y recuperación; pasos, borradores, fotos optimizadas, planos y enlaces opcionales, mapa y vista previa.
3. CRM y publicación: revisar y corregir, verificar representación y zona, registrar opinión de valor, aceptar dummy desde la cuenta, publicar y tramitar solicitudes. Mantener seis meses y despublicar al vencer.
4. Validación: pruebas de autorización, CSRF, deduplicación, revisión, caducidad, privacidad, imágenes y monedas; suite existente, tipos y compilación. No enviar mensajes reales de prueba ni reiniciar la plataforma activa para validar.

## Decisiones técnicas

Actualización de alcance del 15 de noviembre de 2026: Guillermo eligió Google Places y Google Maps para BETA/RC, aceptó consultas mínimas de dirección al proveedor y la separación de resultados temporales. Esa decisión sustituye la restricción anterior de no usar geocodificación externa para esta integración; el código actual todavía usa Leaflet/OSM. El [plan de ubicación con Google](google-ubicacion-incremento-6.md) registra alcance, pruebas y detalles pendientes antes de activar el nuevo proveedor.

- Reutilizar usuarios y sesiones Django, sin conceder permisos staff a las cuentas del propietario. Cada consulta de captación y archivo comprueba titular de cuenta o staff.
- Persistir el formulario con esquema validado y revisión para evitar sobrescrituras. Cambios de contenido posteriores a revisión invalidan la aceptación anterior y despublican antes de revisar de nuevo.
- Normalizar fotografías en backend con Pillow y soporte HEIC. El navegador puede reducirlas antes de transferir para ahorrar datos. Orientación corregida, máximo 2400 px, salida WebP sin metadatos del original. Límite interno amplio de 256 MB por carga y protección por píxeles; no pedir compresión manual de fotos normales. Reintento por archivo con identificador estable.
- Archivos fuera del directorio público. Servir por ruta autorizada, incluso tras despublicar o expirar; planes PDF se descargan. Un volumen conserva archivos entre despliegues.
- Email mediante backend configurable de Django o Resend HTTPS. En desarrollo, archivos privados; entrega real requiere configurar proveedor y remitente. Los enlaces de verificación y recuperación no aparecen en respuestas API ni logs y sus tokens viajan en fragmento del enlace. La liga de aprobación usa el UUID de la solicitud y requiere autorización por cuenta.
- Entregas de email y Telegram registradas antes del envío, con resultado incierto sin reenvío automático. Reintento manual de fallos conocidos; un correo local puede encolarse para entrega real una vez configurado el proveedor. Resend usa idempotencia y confirmaciones firmadas de entrega.
- Ubicación exacta privada. La proyección pública redondea coordenadas por defecto y omite dirección exacta. Mapa con Leaflet y atribución de OpenStreetMap; sin geocodificación automática que transmita la dirección privada a un tercero.
- Presupuestos filtran una sola moneda, MXN por defecto si no se declaró otra. Sin presupuesto, el inventario puede mostrar ambas monedas con etiquetas explícitas.
- El vencimiento se mantiene en la cola existente cada minuto. Las consultas públicas comprueban vigencia directamente para no exponer una propiedad entre ejecuciones del mantenimiento.

## Estado

Implementación y validación técnica disponibles. La instancia local incorporó las migraciones `0008`–`0010`: captación, copia de contrato y seguimiento de correo. Resend está preparado, con activación externa todavía pendiente. Se corrigieron la orientación de revisión en CRM, el acceso desde el correo y el contexto al empezar otra solicitud; se mejoraron cuenta, foco y presentación móvil. Ver [evidencia y pendientes](../testing/sexto-incremento.md) y [activación de correo](../testing/resend-beta.md). La aceptación manual del incremento sigue pendiente.
