# EasyBroker: implementación y aceptación

22 de noviembre de 2026. Implementación local del [diseño aprobado](../design/easybroker-modelo-tecnico.md). **Aceptación operativa pendiente.** No se conectaron cuentas reales ni se desplegaron imágenes nuevas de los servicios.

## Comportamiento implementado

- Conexiones independientes con clave cifrada, huella privada para duplicados, responsable predeterminado y control administrativo.
- Actualización horaria/manual en la cola existente, lotes de una petición, límite global conservador de dos peticiones por segundo, reintentos reprogramados y bloqueo global de ejecución. Cada lote dispone de un arrendamiento de 15 segundos; el cliente limita las peticiones y el tamaño de respuesta.
- Estados ordinarios y detalle con revisión de esquema/paginación. Un fallo, una ausencia en páginas móviles o un 404 no crea una baja. La frescura solo avanza con un detalle y estado coherentes de la propia ficha.
- Fichas privadas conservadas aunque sean incompatibles. Correspondencia explícita de tipos, venta/renta independientes, decimales exactos, ausencia distinta de nulo y ninguna conversión de unidades o monedas.
- Revisión humana de ubicación y texto público. La API ordinaria entrega `location.name`; no se divide por comas ni se trata como el esquema geográfico de partners.
- Precio oculto como «Precio por consultar», fuera de filtros monetarios y sin usar su importe privado para ordenar. Coordenadas, dirección exacta y JSON sin revisar no tienen salida pública.
- Exclusiones independientes, baja externa y desconexión con revisión antes de republicar. Recuperación automática solo por caducidad, sin levantar bloqueos humanos.
- Vinculaciones con historia, fuente principal explícita y ninguna sustitución automática. Vincular una oferta local no cambia sus datos, captación ni contratos.
- Tarjetas importadas persistidas como referencias, sin fotos históricas; lectura pública y memoria vuelven a comprobar la revisión. Una respuesta pendiente con hechos restringidos se sustituye o bloquea antes de entregarse.
- Interés y citas revalidan la misma disponibilidad. Las visitas existentes se conservan y los avisos de despublicación usan `notify_client=False`.
- Evidencia externa en cierres y congelación de hechos al confirmar. El importador conserva observaciones posteriores sin reescribir la operación ni la oferta cerrada.

## Evidencia obtenida

Validación tras la [consolidación de arquitectura](refactorizacion-easybroker.md): **347 pruebas de backend aprobadas, 2 omitidas**, incluidas 41 de EasyBroker. `ruff check`, comprobación de Django y detección de migraciones pendientes sin errores. OpenAPI sin cambios; comprobación de tipos, compilación y pruebas del frontend aprobadas, incluidas ocho pruebas de la sesión de revisión.

`backend/tests/test_easybroker.py` cubre cuentas separadas, claves duplicadas, idempotencia, venta/renta del mismo inmueble, restricciones monetarias, el límite exacto de 24 horas, bajas, reconexión, recuperación de caducidad, fallo aislado, 404, origen obsoleto tras desconectar, permisos/CSRF/revisiones, conservación de fuentes, historial público/memoria, cierre congelado y validación final de WhatsApp. También comprueba lectura sin tarjeta seguida de un cambio de privacidad antes de comprometer la respuesta.

La ampliación de fallos comprueba 401/403/404/429/500/503, `Retry-After` numérico y como fecha HTTP, JSON malformado y constantes no válidas, agotamiento de reintentos sin éxito ficticio y recuperación de un arrendamiento sin aceptar escrituras del trabajador antiguo. Los reintentos liberan el ejecutor y conservan las fechas de comprobación. Dos conexiones independientes a PostgreSQL compiten por elegir la fuente principal: una aplica y la otra recibe conflicto tras revalidar las fuentes bloqueadas. Repetir la solicitud ganadora devuelve el resultado guardado aunque su vínculo anterior ya esté inactivo.

El cliente nuevo consultó por GET el sandbox oficial: página de 100 estados con continuación válida y un detalle normalizado, con 12 imágenes vigentes. La respuesta contenía coordenadas privadas; no se publican ni se incorporan URLs de imágenes a las revisiones comerciales. Evidencia temporal sin claves ni datos precisos: `/tmp/maia-eb-client-proof.json`. Esta muestra valida el contrato ordinario utilizado, no los permisos de cuentas reales.

Las migraciones `0018_easybroker_imports`, `0019_easybroker_continuity` y `0020_easybroker_public_evidence` se aplicaron localmente. Antes/después se compararon las 45 tablas existentes y sus 744 filas con los mismos campos: cero diferencias. Las huellas temporales contienen nombres de columnas, conteos y hashes, sin valores de las filas. No se borró ni reatribuyó historia anterior.

El frontend compila y pasa comprobación de tipos. Sus pruebas existentes pasan. Se inspeccionaron la pestaña y el formulario de revisión en el navegador contra respuestas ficticias aisladas; no se enviaron formularios de cuentas reales. El proxy de la plataforma ya arrancada creó y recuperó una conversación sin llamar al modelo. Esa comprobación corresponde a los servicios ya en ejecución, no prueba que ejecuten la imagen nueva.

## Configuración y recorrido pendiente

1. Preparar `EASYBROKER_ENCRYPTION_KEY` en servidor y worker, independiente de Calendar; custodiar la clave y su respaldo por separado. No escribir claves en Git ni en historial comercial. Su pérdida requiere reconectar las cuentas.
2. Actualizar los servicios con este código, ejecutar las migraciones previstas y comprobar nuevamente las rutas por el proxy. Mantener `EASYBROKER_PUBLIC_ENABLED=false` mientras se verifica la aceptación.
3. Un administrador conecta dos cuentas reales autorizadas desde CRM → EasyBroker. El entorno de cada conexión es explícito. Una organización nueva necesita otra conexión; una rotación no aplica datos hasta demostrar continuidad con un identificador conocido. Si esa prueba es ambigua, permanece bloqueada y requiere corregir la conexión.
4. Esperar la actualización de ambas cuentas y comparar una muestra con el proveedor. Comprobar procedencia, responsable, registros pendientes y reimportación sin duplicados. Los hechos actuales están en la ficha de importación; la tabla general identifica la última oferta aplicada. `source_current` y el perfil de cierre evitan usar esa materialización anterior como hechos actuales cuando el origen pierde datos.
5. Revisar ubicación, texto y operación; las ofertas seguirán privadas por la bandera de aceptación. Comprobar vínculos locales, fuente principal, exclusiones manuales y las restricciones de precio/ubicación en los formatos realmente presentes.
6. Medir tiempo de barrido, crecimiento de cola y latencia de chat/citas con el worker real de cuatro ejecutores y el volumen de las dos cuentas. Las pruebas de lotes y bloqueo no sustituyen esta medición de carga. Ajustar capacidad o cadencia si el barrido no cabe en una hora.
7. Repetir los fallos controlados con el worker real y su transporte, sin alterar anuncios externos: 429/5xx/timeouts, recuperación de un lote interrumpido, fallos de cuenta aislados y cambio de configuración durante una consulta. Los casos automatizados ya comprueban la política; queda verificar su operación bajo carga. Repetir recorridos públicos, historial y entrega pendiente; las restricciones deben regir también después de recargar.
8. Completar la aceptación humana en móvil y teclado, verificar las fotos reales y sus fallos. Activar publicación solo tras registrar la evidencia de privacidad, concurrencia y carga que exige el diseño.

Desactivar la exposición mantiene la integración privada, pero no autoriza volver a una versión antigua que ignore procedencia o privacidad. Las tres migraciones son aditivas; no se ha ensayado una reversión destructiva sobre la base de trabajo.
