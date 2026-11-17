# Google Maps y Places: activación y validación de BETA

Implementación del incremento 6, 15 de noviembre de 2026. Google está activado en el sandbox desde el 15 de noviembre de 2026. Las pruebas automatizadas usan transporte simulado; la comprobación real se registra abajo. La instancia conserva la alternativa manual si Google no está disponible.

Verificación realizada: suite de regresión backend de 245 casos aprobados y dos opcionales omitidos; después pasaron los 16 casos focalizados finales de ubicación, incluido guardar → cerrar sesión → login por contraseña → recuperar borrador y rechazo de la segunda cuenta. Doce pruebas frontend aprobadas, seis del chat y seis de autorización/restauración del borrador local. Tipos, compilación, Ruff, comprobación de migraciones y proxy real aprobados. Se comprobó en navegador el formulario manual, su recuperación local al recargar y el caso rural sin calle/colonia; a 390 px no hubo desbordamiento. La comprobación inicial real de mapa y proveedor quedó aprobada; falta validar sugerencias y selección en una sesión propietaria autenticada. Evidencia local: `/tmp/maia-google-location/ubicacion-movil.png`.

El borrador local se vincula a la cuenta y toda captación ya guardada exige una lectura autorizada antes de restaurarse en pantalla. Si no puede autorizarse, no se muestra su contenido; un fallo de conexión no borra automáticamente el registro local. Los formularios anónimos nuevos pueden continuar al crear cuenta. El borrador conserva la revisión anterior para que una escritura concurrente no sobrescriba cambios silenciosamente.

## Activación real del sandbox, 15 de noviembre de 2026

- Proyecto Google Cloud: `Maia` (`maia-514000`), con facturación existente por consumo. Maps JavaScript API y Places API (New) habilitadas; ambas respondieron correctamente.
- Clave `Maia BETA - Navegador`: solo Maps JavaScript API y orígenes `https://sandbox.elmenlabs.com`, `http://localhost:3000`, `http://127.0.0.1:3000`.
- Clave separada `Maia BETA - Servidor`: solo Places API (New), privada. Falta restringirla por IP cuando el despliegue tenga una salida fija confirmada; no se presupone fija la conexión local.
- Ambas claves guardadas, con autorización de Guillermo, en `.local/google-maps.env`, permisos `600` y archivo ignorado por Git. No se incluyeron valores en documentación ni se leyó la configuración principal.
- Backend y worker recreados con los tres archivos Compose. `google_location_status` confirmó ambas claves presentes y configuración activa.
- El mapa Google cargó en el formulario público del sandbox. Una consulta real del backend para el punto público Catedral de Guadalajara devolvió cuatro sugerencias y detalle con coordenadas. No se creó ni publicó una propiedad. Google no devolvió municipio para ese resultado: el formulario debe permitir completarlo manualmente, sin inventarlo.
- Cuotas diarias del proyecto reducidas y confirmadas en Google Cloud: `AutocompletePlacesRequest` **300**, `GetPlaceRequest` **90**, `SearchTextRequest` **30**, `Map loads` **90**. Se conservan también los límites mensuales de la aplicación. Estos topes diarios pueden obligar a usar captura manual antes del tope mensual.
- Alerta mensual `Maia BETA - Alerta mensual`, importe **$10**, solo proyecto Maia, avisos al **50%, 90% y 100%** para administradores y usuarios de facturación, guardada con autorización. La consola mostró `$0.00 / $10.00`; no se cambió el plan ni se configuró un corte de gasto.
- Guillermo confirmó que el autocompletado funcionó después de iniciar sesión; reportó municipio vacío. Se mantiene municipio estricto por su decisión: si Google lo omite, se captura manualmente, sin aviso adicional por petición de Guillermo. La prueba de recuperación del borrador sigue pendiente de aceptación manual. Tras simplificar el formulario, se verificaron en el sandbox sugerencias y selección reales de un punto público: Google completó calle, estado, colonia y punto; al omitir municipio, apareció el aviso específico y el campo quedó requerido y vacío. Se verificó la ausencia de los textos/enlaces adicionales y de la entrada de coordenadas. TypeScript, compilación del frontend y la prueba existente de no sustituir localidad por municipio aprobaron. Evidencia: `/tmp/maia-google-setup/ubicacion-simplificada.png`. No se guardó ni envió una captación durante esa comprobación.
- Antes de RC: Map ID propio, revisar salida fija y restricciones por IP, términos/aviso de privacidad propios y comprobaciones de privacidad del recorrido manual.

Evidencias locales de configuración y mapa: `/tmp/maia-google-setup/clave-navegador-restringida.png`, `/tmp/maia-google-setup/alerta-guardada.png`, `/tmp/maia-google-setup/cuota-mapas-guardada.png`, `/tmp/maia-google-setup/mapa-google-activo.png`. No contienen claves.

## Configuración sin exponer claves

Desde la raíz:

```bash
cd /Users/el-men/Workspace/maia-agent
./scripts/setup-google-maps-beta.sh
```

El asistente guía proyecto/facturación, Maps JavaScript API y Places API (New), clave del navegador y clave del servidor. Usa entrada oculta y guarda solo `.local/google-maps.env`, ignorado por Git y con permisos privados. No lee ni modifica la configuración principal, activa servicios, contrata ni consulta domicilios por su cuenta. Comprobado con `bash -n`, sin ejecutar su recorrido de credenciales.

- **Navegador:** Maps JavaScript API y restricción por sitios web. Autorizar los orígenes de BETA y localhost que se usarán; el cargador utiliza `auth_referrer_policy=origin`. Esta clave será visible en el navegador.
- **Servidor:** otra clave, restringida a Places API (New); restringir además IP de salida si es fija. No entregarla al frontend ni pegarla en el chat.
- `GOOGLE_MAPS_MAP_ID` es opcional. Para BETA se utiliza `DEMO_MAP_ID` si no hay uno configurado; crear un Map ID propio antes de RC según la guía del proveedor.
- Publicar/revisar los términos y el aviso de privacidad propios de la plataforma que correspondan al uso de Google antes de abrir el piloto a clientes. El formulario conserva la atribución de las sugerencias y del mapa. Se retiraron, por petición de Guillermo, la explicación repetida junto al buscador y los enlaces adicionales de Google; esto no sustituye los documentos propios pendientes.

Activación conservando Resend:

```bash
cd /Users/el-men/Workspace/maia-agent
docker compose -f compose.yaml -f compose.resend.yaml -f compose.google.yaml up -d --no-deps backend worker
docker compose -f compose.yaml -f compose.resend.yaml -f compose.google.yaml exec -T backend python manage.py google_location_status
```

`configured` comprueba presencia, no validez, facturación, restricciones ni APIs habilitadas. Usa los tres archivos al actualizar backend/worker para conservar ambos proveedores. El website obtiene la configuración en tiempo de ejecución; las claves del servidor no se incluyen en su imagen.

## Consumo y límites

El backend reserva una unidad antes de cada consulta o carga de mapa. Cuenta también errores y reintentos, de manera conservadora. Los límites son compartidos por todas las instancias mediante PostgreSQL y se reinician por mes UTC; además hay límites de frecuencia por sesión/cuenta o IP anonimizada según la operación.

| Variable opcional | Límite inicial mensual | Qué incluye |
|---|---:|---|
| `GOOGLE_LOCATION_AUTOCOMPLETE_LIMIT` | 10,000 | Consultas tras esperar 400 ms; sin restricción rígida a Guadalajara |
| `GOOGLE_LOCATION_DETAILS_LIMIT` | 3,000 | Selecciones y actualizaciones técnicas de puntos |
| `GOOGLE_LOCATION_MAPS_LIMIT` | 3,000 | Inicializaciones solicitadas del mapa, incluidas fichas públicas |
| `GOOGLE_LOCATION_ZONE_LIMIT` | 1,000 | Text Search para resolver zonas públicas, reutilizadas durante su vigencia |

El cálculo inicial de investigación no incluía Text Search de zonas públicas. Esta integración sí lo utiliza para evitar revelar el punto o el identificador privados en un mapa aproximado. Solicita solo `places.id,places.location`, correspondiente a Text Search Pro, con cuota gratuita publicada de 5,000 y primer tramo de $32/1,000 después. Una zona no es una dirección privada; no enviar calle/número a esa operación. [Precios](https://developers.google.com/maps/billing-and-pricing/pricing).

Los límites iniciales quedan por debajo de las cuotas gratuitas publicadas para esos SKUs si siguen disponibles en la cuenta de facturación. **No equivalen a un tope global garantizado de USD 10:** Google agrega otros proyectos/consumos, las claves pueden usarse fuera de la aplicación y una alerta no bloquea cargos. Configurar cuotas del proveedor, restricciones de claves y alerta de USD 10. No elevar límites sin revisar el consumo de la cuenta. Al llegar al límite local se ofrece captura manual; la ficha sigue mostrando los datos públicos aunque no pueda cargar el mapa.

## Retención y corrección del punto

- `GoogleLocation` almacena solamente identificador, coordenadas, fuente, fechas, propietario o clave de zona. No conserva respuestas completas ni sugerencias. El identificador de búsqueda de sesión solo se comparte con el usuario autorizado.
- Vigencia del punto: 29 días. Cada hora, `maintain_google_locations` elimina coordenadas vencidas y actualiza, antes del vencimiento, puntos automáticos todavía referenciados por captaciones activas. Cada consulta de detalle también respeta el límite mensual.
- Un ajuste hecho en el mapa tiene la misma vigencia conservadora, pero **nunca se actualiza al punto original de Google**: vencido, exige volver a señalarlo. No se declara conservación indefinida del ajuste. La entrada avanzada de coordenadas se retiró del formulario por petición de Guillermo. Se conserva compatibilidad con coordenadas propias ya registradas; los nuevos puntos se eligen en el mapa.
- El vencimiento no cambia contrato, revisión comercial ni aceptación. Si una ubicación manual vencida necesita corregirse en una captación ya revisada, se usa la corrección del CRM y el flujo de revisión correspondiente.
- Los datos declarados de dirección se confirman al continuar; la aplicación no afirma que una sugerencia verifique el inmueble. Usar la excepción de dirección del usuario exige que realmente corresponda a una dirección propia que el usuario habría proporcionado; no autoriza extraer otras bases de datos de Google. La correspondencia entre componentes mexicanos sigue sujeta a validación real.
- La captación conserva una referencia privada, nunca las coordenadas Google en `Capture.data`. Los contratos y adjuntos no conservan esa referencia. Propiedad y fichas del chat conservan un indicador de consulta, no el punto Google. El navegador omite el resultado temporal al persistir su borrador y lo recupera por una ruta autorizada.
- La zona pública se resuelve separadamente; no se envía la dirección, punto ni identificador privados al navegador para disimularlos después.
- Mantener el worker activo y comprobar `expired_points_awaiting_purge`. La limpieza horaria deja margen frente al máximo de 30 días. Respaldos/exportaciones deben excluir los campos temporales de `GoogleLocation` o tener retención compatible; una restauración debe purgarlos antes de servir tráfico. No se configuró un sistema de respaldos externos como parte de esta integración.

## Retomar desde la prueba 5

Guillermo indicó que estaba en la **prueba 5**, al capturar ubicación. Esto registra su punto para retomar; no marca automáticamente las pruebas anteriores como aprobadas.

1. Con la cuenta propietaria, abrir/crear un borrador, llenar ubicación y pulsar Guardar y salir. Cerrar sesión, volver a entrar y abrirlo: debe conservar los datos declarados. Con Google activo, recuperar el punto por su referencia privada.
2. Desde una segunda cuenta, intentar abrir la solicitud y sus archivos: debe rechazarlos. El identificador del resultado de ubicación tampoco autoriza a leerlo desde otra cuenta.
3. Con Google activo, escribir dirección, elegir sugerencia y comprobar estado/municipio/colonia y punto. Guillermo confirmó mantener municipio estricto: no sustituirlo por ciudad/localidad. Si Google lo omite, conservar el campo vacío y obligatorio, sin aviso adicional. Corregir campos incompletos y confirmar ubicación al continuar. Si se cambia calle o estado, se invalida el punto anterior hasta volver a localizarlo. Completar o corregir municipio/colonia conserva el marcador y su referencia privada, pero exige confirmar de nuevo la ubicación.
4. Probar calle homónima, dirección fuera de Jalisco, número o colonia ausentes y un rancho sin dirección convencional. No exigir colonia inventada: usar referencia y punto en este último caso.
5. Repetir con cuota agotada o Google no disponible: debe conservar el formulario y permitir la alternativa manual. Comprobar que no hay un pin inicial que parezca una dirección localizada.
6. Comprobar ficha pública aproximada y autorización de punto exacto desde CRM, revisando que las respuestas públicas no expongan datos privados.

Después continuar las pruebas 6–12 del [recorrido de aceptación](sexto-incremento-recorrido-manual.md). No repetir aceptación/publicación reales para comprobar solamente el mapa.

## Referencias

- [Cargador JavaScript y claves](https://developers.google.com/maps/documentation/javascript/load-maps-js-api).
- [Marcadores avanzados y Map ID](https://developers.google.com/maps/documentation/javascript/advanced-markers/start).
- [Políticas y atribución](https://developers.google.com/maps/documentation/places/web-service/policies). El archivo SVG local es el original gris del paquete oficial de atribución, sin modificar.
- [Ubicaciones y actualización](https://developers.google.com/maps/architecture/store-locator/).

## Corrección del marcador que desaparecía al completar el municipio

15 de noviembre de 2026. `LocationFields` reutilizaba la invalidación de calle/estado al editar municipio o colonia: borraba `location_ref` y ambas coordenadas, y llamaba `onLocation(null)`. El mapa conservaba su centro y zoom, por lo que se veía el entorno sin marcador. Se reprodujo con el manejador real del campo: `node scripts/test-location-fields.mjs` falló con `null !== 20.677` antes del cambio. En el mapa real del CRM, colocar el punto mostró un marcador y completar el municipio lo redujo de uno a cero.

Corregido: municipio y colonia conservan el punto y dejan `location_confirmed=false` en el formulario compartido. Calle y estado mantienen su invalidación completa. Cuando no hay punto, la interfaz indica tocar el mapa para colocarlo; cuando existe, indica arrastrar o tocar para ajustar. No se inventa un punto inicial ni se reconstruye uno borrado a partir del centro del mapa. No cambian permisos, retención o almacenamiento.

Las tres regresiones del componente comprueban coordenadas y referencia conservadas al escribir municipio completo y corregir colonia, además de invalidación al cambiar calle/estado. Pasaron las 28 pruebas frontend y la compilación. En Chrome con viewport 440 px, el formulario compartido del CRM mantuvo un marcador antes y después de editar municipio y colonia; arrastrarlo cambió el punto. Se canceló el formulario sin guardar la captación. La sesión de escritorio disponible era staff, por lo que esta prueba interactiva usó la edición de CRM; la prueba del componente cubre el mismo manejador usado por propietarios. Falta la aceptación en el iPhone físico del usuario. Evidencia local: `/tmp/maia-map-pin/punto-visible.png`.

Se revisó la [guía oficial de marcadores arrastrables](https://developers.google.com/maps/documentation/javascript/advanced-markers/draggable-markers): la configuración existente con `gmpDraggable` era correcta; el borrado de coordenadas fue la causa reproducida.
