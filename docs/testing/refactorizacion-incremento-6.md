# Consolidación de arquitectura del incremento 6

Fecha: 16 de noviembre de 2026. Guillermo autorizó las cinco mejoras del informe y commit/push directo a main. La aceptación de las doce pruebas de BETA permanece documentada en [el recorrido manual](sexto-incremento-recorrido-manual.md); no se atribuye una repetición manual completa por esta refactorización.

## Cambios

1. Correspondencia comercial de aprobación y copia de contrato compartida entre creación, aceptación, reintento y entrega. Una referencia temporal Google no vuelve obsoleta una aprobación comercial sin cambios.
2. Edición de ubicación con una sola coordinación de sesiones, confirmación y respuestas tardías.
3. Recorrido del propietario con autorización, continuación tras cuenta, revisiones y protección frente a cambios de cuenta/solicitud.
4. Feedback de validación HTML y remota con identidad de campos; sin depender de frases en español. Foco sobre el monto visible, nunca el campo oculto. Reemplazar un aviso conserva el foco original.
5. Acciones CRM y reconciliación: distinguir escritura confirmada de actualización pendiente del listado.

No hay migraciones nuevas. Se conservan los datos, las rutas y los identificadores públicos, el detalle y estado de los errores existentes, el proveedor Google, las reglas comerciales y la cola idempotente de archivos. El listado opcional de errores añade información compatible para los formularios.

## Comprobaciones automatizadas

- Backend completo: **261 aprobadas, 2 opcionales omitidas**.
- Selección de captación, aprobación, correo y ubicación: **70 aprobadas**.
- Frontend completo: **59 aprobadas**. Incluye 13 de coordinación propietario/CRM, 10 de edición asíncrona y 8 de feedback/transporte con DOM, además de las regresiones existentes.
- Comprobación de tipos aprobada.
- `makemigrations --check --dry-run`: sin cambios.
- Ruff en los archivos Python modificados: aprobado.

Las pruebas de contrato y correo no envían mensajes reales. Se cubren aprobación Google sin cambios, referencias temporales renovadas, contenido comercial cambiado, revisión y momento de aprobación, copias inmutables e idempotencia. Las pruebas asíncronas controlan respuestas fuera de orden y desmontaje; las de DOM cubren foco, limpieza, campos monetarios y repetición de avisos.

## Verificación de compilación y plataforma

- Compilación de backend, worker y frontend completada; servicios activados con Resend y Google.
- `backend/scripts/check_web_routes.py`, desde el Python del backend: creación y lectura por el proxy real aprobadas, HTTP 200 y sin redirección del POST.
- Navegador: validación del acceso CRM vacío y del registro vacío, agrupación de campos y foco correcto al cerrar; propietario autenticado ve sus solicitudes y abre la correcta mediante la liga; ficha pública inexistente presenta el error y permite repetir la consulta.
- No se aceptaron acuerdos, aprobaron solicitudes ni enviaron mensajes como parte de estas comprobaciones. El proxy creó únicamente una conversación vacía de prueba.
- No había sesión staff disponible para repetir la revisión privada en navegador; las acciones de CRM se comprobaron en las pruebas de su módulo y del backend. El recorrido físico completo en iPhone/tablet no se repite automáticamente; la aceptación manual anterior conserva su alcance.
- Evidencia visual local: `/tmp/maia-i6-refactor/validacion.jpg`.

La revisión del contenido a publicar excluyó rutas privadas, datos locales y compilados; la búsqueda de patrones de credenciales no detectó coincidencias entre los archivos preparados.

## Publicación del repositorio

Al iniciar, main conservaba el commit de reinicio y la aplicación actual estaba sin seguimiento. El commit incluye la base actual necesaria y la consolidación. Se excluyen credenciales/configuración privada, archivos locales, dependencias, compilados y ejemplos PDF generados. No se publican secretos ni se cambia de rama.


## Entrega mediante pull request

GitHub rechazó el push directo a main porque exige PR y el check `tests`. Guillermo autorizó publicar una rama y abrir el PR, conservando las protecciones. `.github/workflows/tests.yml` reemplaza el recorrido histórico product/hermes por PostgreSQL 17, Python 3.13 y Node 22 para la estructura actual de Maia. El job se mantiene como `tests` y ejecuta Ruff, comprobación de migraciones, suite backend, pruebas frontend, tipos y compilación con dependencias bloqueadas. No necesita configuración privada ni credenciales de proveedores.


El primer intento de CI detectó que `uv.lock` conservaba referencias de un registro privado y no podía descargar paquetes (HTTP 403). Se regeneraron las fuentes contra PyPI público sin cambiar ninguna versión. `backend/scripts/check_dependency_sources.py` reproduce el problema mediante la inspección del lock y ahora se ejecuta antes de instalar dependencias para impedir su reintroducción.
