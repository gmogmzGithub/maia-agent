# Ubicación de captaciones: implementación actual, OpenStreetMap y alternativas propias

Fecha de consulta: 15 de noviembre de 2026. Investigación para decidir, no implementación ni decisión aprobada de proveedor. Se revisó código y documentación oficial. No se consultó ninguna dirección privada del usuario en servicios de geocodificación, no se usaron claves y no se ejecutó un benchmark.

## Conclusión

Maia puede conservar Leaflet y un mapa basado en OpenStreetMap y añadir un servicio de autocompletado/geocodificación compatible con sus licencias. No hay que sustituir ambos componentes necesariamente. **El Nominatim público no es una opción para autocompletar direcciones privadas:** su política prohíbe autocomplete y pide no enviar información personal/confidencial. Autoalojar un geocodificador es posible, pero traslada costos, mantenimiento y calidad de datos al equipo. Nada de lo investigado demuestra todavía precisión suficiente para números exteriores y colonias de Guadalajara.

## Lo comprobado en Maia

| Componente | Evidencia de código | Comportamiento actual |
| --- | --- | --- |
| Datos de ubicación | `backend/datalayer/capture_schemas.py:18–24` | Guarda estado, municipio, colonia, subdivisión, dirección privada completa y coordenadas opcionales. No hay campos separados para localidad, CP, calle y número exterior. |
| Formulario | `frontend/src/main-website/pages/OwnerCapture.tsx:879–934` | El propietario escribe cada campo y elige o arrastra el punto. El rótulo «Ciudad o municipio» almacena ambos conceptos en `municipality`. |
| Validación | `backend/datalayer/capture_schemas.py:74–82` | Exige ambas coordenadas o ninguna. La completitud exige municipio, colonia y dirección, pero no exige coordenadas ni verifica existencia de la dirección. |
| Mapa | `frontend/src/shared/components/LocationMap.tsx:24–44` | Leaflet consume `https://tile.openstreetmap.org/{z}/{x}/{y}.png`. Sin coordenadas, centra Guadalajara con zoom 9 y dibuja un pin de todas maneras. Ese pin inicial **no acredita** una ubicación encontrada. |
| Modificación del punto | `LocationMap.tsx:45–53, 67–77` | Clic y arrastre cambian coordenadas. Cambios por props mueven pin y centran con `panTo`, pero no aumentan el zoom inicial. |
| Proyección pública | `backend/datalayer/captures.py:230–263` | Copia municipio y colonia. Omite dirección exacta y redondea coordenadas a dos decimales salvo autorización del equipo; marca `approximate`. |
| Información adicional pública | `backend/datalayer/captures.py:274–275`; `backend/datalayer/inventory.py:20–35` | `subdivision` se proyecta dentro de los detalles; ubicación, colonia y municipio se entregan al catálogo público. |
| Cobertura operativa | `backend/datalayer/captures.py:368–374` | La aprobación fuera de zona se decide usando estado y municipio normalizado. Autocompletar una localidad en el campo municipio puede afectar esa decisión. |

La política previa en `docs/design/plan-sexto-incremento.md:20` establece evitar geocodificación automática que transmita la dirección privada a terceros. Usar un proveedor externo cambiaría esa decisión y requiere acordarlo. La privacidad frente al visitante del catálogo y la transmisión al proveedor son dos asuntos distintos.

`docs/architecture/captacion/README.md:62–64` ya advierte que la autorización de ubicación la registra el equipo, no equivale por sí sola al consentimiento del propietario, y que el redondeo no garantiza anonimato frente a fotos, descripción y referencias.

**Inferencia:** dos decimales producen una cuadrícula de aproximadamente un kilómetro en Guadalajara. Es una transformación de publicación, no la precisión que debería exigirse al punto privado. Las solicitudes de tiles también revelan al proveedor IP y área visualizada, aunque el código no le envía la dirección escrita.

## Son servicios diferentes

- **Leaflet:** biblioteca que presenta el mapa y maneja marcadores; su documentación trata la geocodificación como integración con servicios externos. [Documentación oficial de plugins](https://leafletjs.com/plugins.html#geocoding), contrastada con Context7 `/leaflet/leaflet`.
- **OpenStreetMap:** base cartográfica abierta. ODbL exige atribución y puede imponer obligaciones al distribuir bases derivadas. Que el dato sea abierto no convierte sus servidores públicos en infraestructura ilimitada. [Licencia oficial](https://www.openstreetmap.org/copyright).
- **Tiles:** imágenes o vectores del mapa visible. Su proveedor y tarifa pueden ser distintos del proveedor de búsqueda.
- **Autocompletado:** sugiere candidatos mientras se escribe.
- **Geocodificación:** obtiene coordenadas y componentes a partir de una dirección. La inversa obtiene una descripción desde coordenadas. Ninguna certifica propiedad, existencia física actual o identidad del dueño.

## Servicios públicos de OSM

### Nominatim público

La política aplica a `nominatim.openstreetmap.org`, no a instancias propias ni proveedores terceros. Prohíbe autocomplete, limita el uso total de la aplicación a un máximo de una solicitud por segundo, exige identificar la aplicación y atribución, y solicita no enviar datos personales o confidenciales. Puede restringir acceso; no es una base adecuada para esta función de Maia. Tener pocos usuarios o poner un proxy no levanta esas restricciones. [Política oficial](https://operations.osmfoundation.org/policies/nominatim/).

### Tiles públicos

El uso interactivo normal requiere atribución visible, Referer válido desde web y respetar caché HTTP. No se permiten descargas masivas ni precarga offline. La política pide permitir cambio de servicio y advierte que el acceso puede retirarse. El cliente actual muestra atribución y usa la URL HTTPS correcta, pero tiene el proveedor fijo en el componente. La disponibilidad de la aplicación comercial no debe depender indefinidamente de este servicio donado. [Política de tiles](https://operations.osmfoundation.org/policies/tiles/).

## Autoalojamiento

| Motor | Capacidad y exigencias verificadas | Implicación para Maia |
| --- | --- | --- |
| Nominatim | Usa PostgreSQL/PostGIS; mínimo de instalación 2 GB RAM. La guía recomienda 128 GB RAM y al menos 1 TB de disco para el planeta completo, con importación de días. | Un extracto regional reduce recursos, pero hay que medir México. No ofrece por sí solo la experiencia search-as-you-type buscada. [Instalación oficial](https://nominatim.org/release-docs/latest/admin/Installation/). |
| Photon | Soporta búsqueda mientras se escribe, tolerancia a errores, sesgo geográfico y geocodificación inversa; usa OpenSearch y datos OSM. El README indica unos 95 GB de base planetaria y recomienda 64 GB RAM; actualizar dumps necesita espacio adicional. Su demo no garantiza disponibilidad y puede limitar o bloquear uso intensivo. | Alternativa propia más directa para autocomplete. Software Apache 2.0, con obligaciones separadas para los datos. No usar la demo como dependencia comercial asumida ni asumir cobertura de todas las puertas. [Repositorio oficial](https://github.com/komoot/photon). |
| Pelias | Tiene autocomplete, búsqueda estructurada y detalles. Puede importar distintas fuentes, incluidas OSM, OpenAddresses y Who's on First; las licencias de cada origen siguen aplicando. | Flexible para combinar fuentes locales, con mayor operación. No asumir que agregar motores crea numeraciones que faltan en los datos. [Documentación](https://github.com/pelias/documentation), [fuentes](https://github.com/pelias/documentation/blob/master/data-sources.md). |

Pelias distingue instalaciones pequeñas del planeta completo; sus guías de importación y producción requieren gestionar servicios e índices y recomiendan separar importación de consultas. Los tamaños planetarios citados **no son requisitos calculados para Guadalajara ni cotizaciones de México**. [Instalación](https://github.com/pelias/documentation/blob/master/getting_started_install.md), [consideraciones planetarias](https://github.com/pelias/documentation/blob/master/full_planet_considerations.md).

**Referencia de costo de infraestructura, no presupuesto validado:** DigitalOcean publica VMs Basic de 4 GB/80 GB por USD 24/mes, 8 GB/160 GB por USD 48 y 16 GB/320 GB por USD 96. Una prueba regional podría explorar esos tamaños, pero no se comprobó cuál basta. Agregar disco, respaldos, observabilidad, actualizaciones, seguridad, importaciones, disponibilidad y tiempo del equipo. Un despliegue propio no cuesta cero ni garantiza mejor calidad que una API comercial. [Precios oficiales](https://www.digitalocean.com/pricing/droplets).

## SEPOMEX e INEGI como complementos

Correos de México permite descargar el catálogo por estado o país en TXT/XML/Excel y relaciona CP, estado, municipio y asentamiento. Advierte que el catálogo es gratuito y no permite su comercialización total o parcial; revisar esa condición para el uso concreto. Sirve como catálogo complementario, no demuestra coordenadas de cada número exterior. No confundir descargar una tabla postal con contar con autocomplete completo de domicilios. [Consulta](https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/Descarga.aspx), [descarga](https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/CodigoPostal_Exportar.aspx).

El Catálogo Único de INEGI aporta claves/nombres de estados, municipios, localidades, asentamientos y vialidades; ofrece JSON y algunas geometrías. Es útil para homologar divisiones, no acredita precisión de puerta para una dirección libre. Su documentación distingue localidad de municipio; Maia no debería mezclarlos automáticamente. [Servicio oficial](https://www.inegi.org.mx/servicios/catalogoUnico.html). La [norma de domicilios](https://snieg.inegi.org.mx/Documentos/Normatividad/Vigente/Norma_Tecnica_sobre_Domicilios_Geograficos.pdf) también contempla entornos rurales sin numeración regular.

## Diseño propuesto, pendiente de decisión

1. Mantener separados dirección escrita por el usuario, candidato del proveedor y dirección/punto confirmados. No reemplazar una corrección manual con una respuesta tardía del buscador.
2. Agregar autocompletado junto al campo de dirección en el módulo del website. Debounce, mínimo de caracteres, cancelación de consultas anteriores y atribución del proveedor, conforme a sus términos.
3. Una frontera pequeña en `backend/api` autoriza y limita solicitudes; un adaptador del proveedor valida resultados. No mandar nombre, teléfono, email ni identificadores de contrato. Enviar solo lo indispensable para buscar la dirección, entendiendo que esa dirección privada sí saldrá al tercero.
4. Seleccionar un candidato llena componentes presentes y centra el mapa al nivel adecuado; no inventa colonia, CP, número exterior ni exactitud de azotea. En México, mapear municipio/estado/localidad/colonia explícitamente según el proveedor. El identificador externo se guarda solo si su licencia permite ese uso.
5. Permitir corregir campos y pin, y conservar una alternativa manual para calles nuevas, predios rurales y fallos del proveedor. Editar la dirección tras elegir candidato invalida el punto automático hasta reconfirmarlo. Mover pin no debe sobrescribir la dirección silenciosamente.
6. Guardar únicamente campos y plazos permitidos por el contrato del servicio elegido. Caché para rendimiento y persistencia del inventario por meses/años son permisos diferentes. No asumir que una casilla «confirmar» convierte automáticamente todo contenido del proveedor en dato propio libre de restricciones.
7. Conservar la proyección pública como proceso independiente: proveedor no controla si la dirección exacta se publica. No guardar consultas completas en logs, analítica o mensajes de error. El frontend no decide permisos de publicación.
8. Revisar `LocationMap`: ocultar el pin falso inicial y, al resolver, ajustar zoom/bounds. Ocultar latitud/longitud del recorrido normal y dejarlas solo como controles avanzados si hay una necesidad real de producto.

## Benchmark propuesto, no ejecutado

Usar un conjunto autorizado de al menos 60–100 direcciones verificadas, con muestra separada para Guadalajara/Zapopan y demás municipios metropolitanos; incluir otros estados, viviendas/comercial/industrial, fraccionamientos nuevos, calles repetidas, acentos/abreviaturas, edificios con interior, CP ambiguo y predios rurales sin número. No usar direcciones privadas reales sin acordar antes la transferencia y los términos del proveedor.

Medir sobre el mismo conjunto y versiones:

- Tasa de candidato correcto en primer resultado y top 5; tasa de no resultado y falsos positivos.
- Exactitud de estado, municipio, localidad, colonia, CP y número exterior **por separado**; distinguir campo faltante de dato incorrecto.
- Porcentaje que completa el formulario sin editar campos ni mover pin.
- Distancia del pin al punto de referencia aprobado: mediana, p90/p95 y porcentajes dentro de 25/50/100 m. Separar rooftop, interpolación de calle y centroide de zona, si el proveedor expone esa precisión.
- Latencia p50/p95, solicitudes facturables reales por formulario, búsquedas abandonadas, selección y reintentos. El costo por captación terminada incluye las que se abandonan.
- Comportamiento con proveedor caído o cuota agotada; teclado, lector de pantalla y celular; resultados tardíos no alteran otra dirección; cobertura fuera de zona base no queda bloqueada por un filtro rígido.
- Permisos de conservación, uso en mapa distinto, atribución y borrado como criterios eliminatorios antes de comparar precio.

Criterios numéricos de aceptación, presupuesto y proveedor siguen pendientes de Guillermo. No hay evidencia para afirmar que Inmuebles24 use Google ni que determinada API sea la más precisa en México sin inspección autorizada y benchmark.

## Seguimiento: auditoría de copias y caducidad al elegir Google

Actualización del 15 de noviembre de 2026: el equipo está evaluando la implementación con Google y Google Maps. Esta sección es una inspección de propagación de datos, **no una conclusión legal** sobre qué campos permite conservar un contrato concreto. Si el producto/contrato aplicable limita determinados resultados a 30 días, no basta con borrar una tabla llamada caché. Hoy no hay metadatos de origen ni expiración por campo que permitan distinguir esos resultados de una dirección declarada por el propietario.

### Dónde quedarían copias si se insertaran resultados del proveedor en `Capture.data`

| Destino | Evidencia | Qué permanece hoy y qué revisar |
| --- | --- | --- |
| Captación editable | `backend/datalayer/models.py:448`; `backend/datalayer/captures.py:199–207, 353–358` | `data` recibe el formulario validado entero. Latitud, longitud y todos los componentes del formulario quedan sin vencimiento programado. Correcciones también sustituyen `data` entero. |
| Inventario | `backend/datalayer/models.py:121–131`; `captures.py:230–263, 274–290` | Se copian estado, municipio y colonia a columnas; subdivisión a `details`. La dirección exacta puede copiarse a `public_address`; las coordenadas se copian exactas o redondeadas a `public_location`. Redondear es una transformación, no demuestra independencia del origen ni extinción de restricciones. |
| Acuerdo aceptado | `backend/datalayer/models.py:487–495`; `captures.py:445–454` | `CaptureAgreement.snapshot = capture.data`: copia inmutable completa, incluidas coordenadas aunque el PDF no las imprima. El vencimiento/retirada solo marca terminación; no purga el snapshot (`captures.py:489–499`). |
| Copia pendiente/enviada por correo | `capture_contract.py:17–40`; `captures.py:71–98`; `models.py:506–522` | `CaptureDelivery.attachment` conserva `data` completo y, además, `address` como texto compuesto de dirección, colonia, municipio y estado. No tiene TTL. Los avisos superseded conservan ese contenido. |
| PDF descargado o adjunto | `capture_contract.py:110–119`; `backend/api/capture.py:244–255`; `worker/capture_delivery.py:56–77` | El PDF actual imprime la dirección compuesta, **no imprime latitud/longitud**. Se genera desde snapshot de aprobación o aceptación. Corregir el JSON de origen no recupera PDFs ya descargados. |
| Proveedor de correo/buzón | `backend/worker/capture_email.py:62–77` | El adjunto PDF se transmite a Resend y al destinatario. Los bytes contienen dirección, aunque no coordenadas. Maia no puede prometer borrar las copias del buzón. La retención del proveedor debe revisarse aparte. |
| Correo local opcional | `backend/maia/settings.py:121–122`; `compose.yaml:27,48,65`; `worker/capture_delivery.py:71–93` | El backend de archivos puede conservar MIME+PDF en `private_mail`, volumen persistente. Es una vía opcional según configuración; no se inspeccionaron secretos ni todos los archivos almacenados. |
| Borrador del navegador | `OwnerCapture.tsx:93–102, 132–143` | `sessionStorage` conserva `{id, data, capture}`: puede duplicar dirección y coordenadas dentro de `data` y de `capture.data`. No guarda `expires_at` ni comprueba antigüedad al restaurar. Que sea sessionStorage no acredita un máximo de 30 días: una pestaña/sesión restaurada puede sobrevivir. Se limpia al enviar o salir por los flujos previstos, no por fecha. |
| Historial de fichas del chat | `inventory.py:20–35`; `conversations.py:47–54`; `turns.py:49–63,84–90`; `models.py:209–212` | `public_property` incluye `public_location`, municipio, colonia, dirección pública y detalles. Esa proyección se copia a `Message.properties` al expresar interés o mostrar fichas. Borrar coordenadas de `Property` después no elimina estas copias históricas. `presentation` conserva la estructura de bloques; la copia de propiedades está en `properties`. |
| Eventos y notas | `captures.py:47–48, 419, 477–484`; `models.py:498–503` | `CaptureEvent` no copia automáticamente el formulario: guarda acción y resumen. El resumen y los mensajes son texto libre; un operador/usuario podría pegar una dirección o coordenadas ahí. No se halló un TTL de limpieza de contenido por proveedor. |
| Respaldos/exportaciones | `docs/architecture/captacion/README.md`, pendientes de respaldo/restauración | Todo respaldo de tablas/volúmenes puede contener las copias anteriores. No se comprobó una política de retención externa operativa ni se inspeccionaron backups. Debe incluirse en el diseño de expiración y recuperación. |

No se encontró en el flujo revisado una persistencia automática de las coordenadas de captación dentro de `CaptureMailEvent`: ese registro conserva identificadores/tipo/fechas. Los avisos Telegram de captación generan título/ID y liga al CRM (`captures.py:102–110`), no coordenadas de forma estructurada. Esto no equivale a una auditoría exhaustiva de todo texto libre, observabilidad ni exportaciones existentes.

### Separación mínima propuesta

1. **Inventariar permisos por campo y producto antes de diseñar la retención.** Distinguir coordenadas, dirección formateada/componentes, identificadores externos y datos introducidos independientemente por el propietario. Una confirmación o arrastre del pin no demuestra, por sí solo, que un resultado del proveedor se haya vuelto libre de restricciones.
2. **Datos de proveedor fuera de `Capture.data` y de snapshots comerciales.** Un resultado temporal separado necesita como mínimo proveedor/producto, ID de selección, campos permitidos, `fetched_at` y `expires_at`. Solo guardar sin plazo los identificadores/campos que expresamente permita el contrato. No incrustar una copia del objeto temporal en el borrador del navegador.
3. **Declaración del propietario separada de la procedencia.** `confirmed_at` y quién confirmó registran el acto de confirmación; no sustituyen `source` ni el permiso de retención. La dirección utilizada en contratos debe tener una base de conservación compatible con su permanencia y con los PDFs enviados. Si esa base no está resuelta, no copiar silenciosamente el resultado de Google al contrato.
4. **Snapshots por lista permitida, no `snapshot=capture.data`.** La aprobación, el acuerdo y el correo deben tomar una proyección comercial explícita que excluya contenido temporal o no autorizado. El PDF puede seguir mostrando una dirección si existe una fuente/permisión adecuada; no necesita coordenadas para su formato actual. Separar una huella/revisión comercial de metadatos transitorios para que renovar un resultado técnico no invalide una aprobación: hoy el worker y el reintento comparan el JSON completo (`worker/capture_delivery.py:26–36`; `captures.py:327–337`).
5. **Proyección de mapa vigente, no coordenadas copiadas a todo historial.** Renderizar mapas desde una referencia y un resultado todavía válido donde lo permitan los términos. Si `Property.public_location` conserva material sujeto a plazo, debe tener procedencia/expiración y no propagarse sin control a `Message.properties`. No convertir coordenadas vencidas en ubicación aproximada pensando que eso las elimina.
6. **Expiración de extremo a extremo.** Vencimiento en lectura, depuración programada e impedimento de reintroducción desde sessionStorage, snapshots, colas, mensajes o restauraciones. Considerar suspender el mapa y volver a consultar antes de mostrar un resultado vencido. Si la política elegida no permite mantener determinada dirección dentro de un PDF ya entregado, ese contenido debe excluirse antes del envío; una purga futura no lo resuelve.

### Evidencia mínima antes de afirmar que funciona

- Matriz documentada de campo → origen → permiso → plazo → todas sus copias.
- Test con resultado de proveedor y reloj controlado: después del plazo ya no aparece en `Capture.data`, `Property.public_location`/componentes afectados, acuerdos, entregas, borrador del navegador ni `Message.properties`. Las rutas antiguas, reintentos y restauraciones tampoco lo reintroducen.
- Test que demuestra que el snapshot/PDF nunca recibió coordenadas ni otros campos temporales; otro que comprueba que el contenido comercial autorizado sigue siendo reproducible e inmutable tras expirar la consulta técnica.
- Inventario de posibles adjuntos locales, copias en Resend y respaldos, con alcance comprobado y límites explícitos. No prometer borrado de PDFs que el destinatario ya descargó.
- Registro de depuración con IDs, conteos y fechas, sin conservar los resultados borrados en el propio log.

Estas son propuestas de ingeniería. No prueban que una política de 30 días sea suficiente ni que todos los componentes de Places tengan la misma excepción que Geocoding. Esa conclusión exige contrastar el producto, campos y términos concretos. Tampoco procede purgar contratos existentes por una regla hipotética: no se ha identificado una integración Google previa que los haya originado y no se modificaron registros durante esta revisión.

Otros destinos identificados en el seguimiento: `Property.save()` también construye `normalized_zone` desde municipio y colonia (`backend/datalayer/models.py:154–156`); el título por defecto incorpora la colonia (`captures.py:250`). La presentación textual de fichas incluye colonia y municipio (`backend/harness/presentation/properties.py:62–72`), por lo que esas cadenas pueden terminar en mensajes históricos y entregas, además del JSON. Al coordinar visitas, `worker/appointments.py:56–67` copia `Property.public_address` al campo `location` del evento de calendario: otro destino externo que una purga de la base de Maia no revoca automáticamente. Estas rutas no agregan una copia estructurada de latitud/longitud, pero sí importan si algún componente textual tiene un permiso limitado.
