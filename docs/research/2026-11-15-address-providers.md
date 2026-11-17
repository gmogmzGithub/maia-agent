# Proveedores de autocompletado y geocodificación para Maia

Investigación documental del 15 de noviembre de 2026. Solo fuentes oficiales. No se contrataron servicios, crearon cuentas ni enviaron direcciones del usuario a una API de ubicación. No se midió precisión en Guadalajara ni latencia real. Importes en USD, sin impuestos, salvo donde se indique otra moneda. Los precios pueden cambiar.

## Resultado

Para conservar Leaflet y el mapa basado en OpenStreetMap, **Geoapify y LocationIQ son los primeros candidatos a una prueba comparativa**. Ambos documentan autocompletado con coordenadas y componentes en la respuesta y permiten conservar datos, con atribución. La calidad local sigue sin comprobarse. La selección debe depender de direcciones mexicanas conocidas, no de afirmaciones comerciales de cobertura mundial. [Geoapify API](https://apidocs.geoapify.com/docs/geocoding/address-autocomplete/), [LocationIQ API](https://docs.locationiq.com/docs/autocomplete), [Geoapify almacenamiento](https://www.geoapify.com/geocoding-api/), [LocationIQ condiciones prácticas](https://locationiq.com/pricing).

**Mapbox Search Box no es intercambiable con Mapbox Geocoding permanente**: Search Box declara cobertura en Estados Unidos, Canadá y Europa, usa suggest/retrieve y sus resultados son temporales. No recomendarlo para almacenar inmuebles mexicanos. [Search Box](https://docs.mapbox.com/api/search/search-box/).

Mapbox Geocoding sí tiene modo permanente, pero su documentación exige usar sus respuestas junto con un mapa Mapbox. Guardado permitido no equivale a uso autorizado sobre cualquier mapa. Maia necesitaría cambiar el proveedor de mapa o conseguir condiciones específicas. [Geocoding v6, almacenamiento y precios](https://docs.mapbox.com/api/search/geocoding/).

## Comparación

| Servicio | Cobro y plan de entrada | Guardado del resultado seleccionado | Encaje con el mapa actual |
| --- | --- | --- | --- |
| Geoapify Address Autocomplete | 1 crédito por llamada; 3,000 créditos/día gratis, 5 solicitudes/s; API 10: $59/mes, 10,000 créditos/día | El proveedor no impone un límite temporal; mantener atribución de las fuentes | API independiente del visor, compatible con Leaflet y otros mapas |
| LocationIQ Autocomplete | Free: 5,000 solicitudes/día, 2/s y 60/min; Developer: $100/mes, 25,000/día, 20/s | Su FAQ permite conservar datos de respuesta indefinidamente; distingue la caché de pares petición/respuesta, que en Free dura como máximo 48 h | Candidato para Leaflet; conservar atribuciones del resultado y enlace visible exigido en Free |
| Mapbox Search Box | Por sesión suggest/retrieve; tarifas estándar y preview diferentes | Temporal; almacenamiento requiere conversación comercial | No candidato de partida: México no figura en la cobertura publicada |
| Mapbox Geocoding v6 permanente | $5 por 1,000 llamadas hasta 500,000; sin cuota gratis permanente | Indefinido con `permanent=true`; tarjeta válida o contrato empresarial | Su documentación exige mapa Mapbox |
| HERE | No se pudo verificar la tarifa actual en la página directa de precios; respondió 403 durante la investigación | La oferta publicada por HERE en AWS separa la geocodificación permanente de la oferta ordinaria | Requiere aclarar contrato de permanencia y visualización antes de estimar para Maia |
| TomTom | Pricing actual publica 10,000 Suggest, 5,000 Details y 20,000 Geocoding gratis al mes, por API | No se verificó un derecho de almacenamiento permanente en los términos accesibles | Mantener como alternativa a cotizar, sin tratar su cuota gratis como permiso de persistencia |

Fuentes de la tabla: [Geoapify precios](https://www.geoapify.com/pricing/), [Geoapify coste por API](https://www.geoapify.com/pricing-details/), [Geoapify almacenamiento](https://www.geoapify.com/geocoding-api/), [Geoapify compatibilidad](https://www.geoapify.com/), [LocationIQ precios y FAQ de caché](https://locationiq.com/pricing), [Mapbox precios](https://www.mapbox.com/pricing), [Mapbox Search Box](https://docs.mapbox.com/api/search/search-box/), [Mapbox Geocoding](https://docs.mapbox.com/api/search/geocoding/), [oferta de HERE en AWS](https://aws.amazon.com/marketplace/pp/prodview-2ycujvbhl27am), [TomTom precios](https://docs.tomtom.com/pricing).

## Geoapify: detalles que cambian la decisión

La respuesta de autocomplete ya contiene `lat`, `lon`, calle, número, estado, ciudad y otros componentes disponibles, además del tipo de resultado y señales de confianza. Se puede filtrar por país y dar preferencia a una zona mediante `bias`; preferir Guadalajara no requiere excluir el resto de México. Algunos campos pueden faltar. Seleccionar una sugerencia no exige por diseño una llamada equivalente a Place Details: la aplicación puede usar los datos que ya recibió. Esto es una inferencia de su contrato de respuesta, no una prueba ejecutada. [API de autocompletado](https://apidocs.geoapify.com/docs/geocoding/address-autocomplete/).

Una calle encontrada no acredita un número exterior ni una coordenada a nivel de edificio. Para Maia deben distinguirse el punto sugerido por el proveedor, su precisión estimada y el punto confirmado o corregido por el propietario. No deducir automáticamente que `city`, `county`, `suburb` o `district` equivale siempre a municipio o colonia en México. Mantener campos corregibles y faltantes visibles. La API documenta confianza por niveles, no una garantía de existencia o titularidad del inmueble. [Respuesta y confianza de geocodificación](https://apidocs.geoapify.com/docs/geocoding/forward-geocoding/).

El FAQ permite almacenar resultados y exige conservar atribuciones al reutilizarlos. Su página general incluye el uso con Leaflet, MapLibre y otros visores. Esto permite conservar la biblioteca actual; no obliga a comprar sus mapas para usar su búsqueda. [Almacenamiento](https://www.geoapify.com/geocoding-api/), [compatibilidad y reutilización](https://www.geoapify.com/).

El FAQ actual permite Free comercial y en producción dentro de límites. Sus términos de febrero de 2024, más cautos, remiten a contacto sobre limitaciones de producción. Confirmar condiciones aplicables antes del lanzamiento. Atribución a OSM obligatoria; a Geoapify también en Free. [Precios](https://www.geoapify.com/pricing/), [términos](https://www.geoapify.com/terms-and-conditions/).

Su política informa que registra cuerpo de petición, encabezados, IP y hora; para solicitudes exitosas suele conservarlos no más de 24 horas. El servicio usa infraestructura europea y proveedores de red externos. Un proxy propio evita exponer la IP del navegador al geocodificador, pero **no evita que el proveedor reciba la dirección consultada**. No enviar nombres del propietario, email, teléfono ni datos del contrato. [Privacidad](https://www.geoapify.com/privacy-policy/).

## LocationIQ: distinguir datos guardados de caché

El endpoint autocomplete responde con coordenadas y dirección descompuesta; soporta español, filtro de países y preferencias de área. No hace falta una consulta de selección solo para conseguir coordenadas que ya vienen en la sugerencia. `normalizecity` puede sustituir una ciudad faltante por otro nivel administrativo; para Maia sería peligroso tratar esa sustitución como municipio confirmado sin revisar la correspondencia mexicana. [Documentación](https://docs.locationiq.com/docs/autocomplete).

El FAQ permite guardar datos de respuesta indefinidamente, pero limita la caché de pares petición/respuesta: 48 horas en Free y duración de la suscripción en pago. Guardar solo la elección como registro del inmueble, no una caché general perpetua. No cachear tiles en servidor. Maps Lite ($45/mes) solo incluye mapas, no geocodificación. [Precios, licencias y caché](https://locationiq.com/pricing).

Conservar también la licencia/fuente del resultado, no solo el enlace comercial: el proveedor documenta OSM, GeoNames, Who’s On First y OpenAddresses entre sus fuentes. [Atribución](https://locationiq.com/attribution).

## Mapbox: no mezclar productos ni derechos

Search Box agrupa suggest y retrieve en sesiones; las coordenadas llegan en retrieve. Publica tarifas estándar y preview distintas, pero no se presupuesta como solución para Maia por sus restricciones de geografía y persistencia. [Precios](https://www.mapbox.com/pricing), [flujo y restricciones](https://docs.mapbox.com/api/search/search-box/).

Geocoding v6 devuelve dirección y coordenadas en cada búsqueda, admite autocomplete y cobra por llamada. Se necesita `permanent=true` en los resultados que se van a conservar. No hay cuota gratis permanente. No usar el precio del endpoint temporal como si incluyera persistencia. Tampoco asumir que comprar permanencia elimina la restricción publicada de mapa Mapbox o permite revender la base de resultados. [Geocoding](https://docs.mapbox.com/api/search/geocoding/), [diferencias temporal/permanente](https://docs.mapbox.com/help/dive-deeper/understand-temporary-vs-permanent-geocoding/), [precios y uso propio](https://www.mapbox.com/pricing).

## Escenarios de coste

Modelo solicitado: 100, 1,000 o 10,000 propiedades al mes; ocho consultas de autocompletado y una selección por propiedad. Mes de 30 días y tráfico uniforme, sin mapas, reintentos, cambios posteriores, formularios abandonados ni otras APIs. Los límites de velocidad y del día de mayor tráfico deben comprobarse aparte.

### Las selecciones no siempre cuestan otra llamada

En Geoapify y LocationIQ, las ocho respuestas ya contienen coordenadas y componentes. Una selección local da **8N llamadas**, no 9N. Como presupuesto conservador, una consulta extra de validación o reverse geocoding daría 9N; no es un requisito universal. El uso real dependerá de la implementación, la espera entre pulsaciones y el número de cambios del usuario. [Geoapify respuesta](https://apidocs.geoapify.com/docs/geocoding/address-autocomplete/), [LocationIQ respuesta](https://docs.locationiq.com/docs/autocomplete).

| Propiedades/mes | 8N llamadas/mes | Promedio diario 8N | 9N con consulta adicional | Promedio diario 9N |
| --- | ---: | ---: | ---: | ---: |
| 100 | 800 | 26.7 | 900 | 30 |
| 1,000 | 8,000 | 266.7 | 9,000 | 300 |
| 10,000 | 80,000 | 2,666.7 | 90,000 | 3,000 |

| Proveedor y flujo | 100 | 1,000 | 10,000 | Condición |
| --- | ---: | ---: | ---: | --- |
| Geoapify Free, 8N o 9N | $0 | $0 | $0 condicional | No superar 3,000 créditos ningún día; a 10,000 propiedades y 9N no queda margen en el modelo uniforme |
| LocationIQ Free, 8N o 9N | $0 | $0 | $0 condicional | No superar 5,000/día, 2/s ni 60/min; cumplir atribución |
| Mapbox Geocoding permanente, 8N | $4 | $40 | $400 | Cálculo conservador haciendo permanentes todas las búsquedas; mapa y contrato compatibles aparte |
| Mapbox Geocoding permanente, 9N | $4.50 | $45 | $450 | Incluye consulta adicional; sin cuota gratis permanente |

Los valores Mapbox son cálculos propios a $5/1,000 hasta 500,000 llamadas. Los valores gratis son aplicación aritmética de los límites publicados, no presupuestos garantizados para tráfico concentrado. [Mapbox](https://www.mapbox.com/pricing), [Geoapify](https://www.geoapify.com/pricing/), [LocationIQ](https://locationiq.com/pricing).

Si 1,000 formularios llegan en un solo día, 8,000 llamadas ya exceden ambos planes gratis. Un día así cabe en Geoapify API 10 ($59/mes, 10,000/día) y LocationIQ Developer ($100/mes, 25,000/día), sujeto al resto de consumo y a velocidad. No confundir 90,000 créditos teóricos por 30 días con una bolsa mensual transferible en Geoapify. [Planes Geoapify](https://www.geoapify.com/pricing/), [planes LocationIQ](https://locationiq.com/pricing).

Una posible optimización Mapbox sería mostrar resultados temporales y consultar de nuevo en permanente solo la elección final. No se presupuestó como solución elegida: necesita confirmar la equivalencia del resultado, las condiciones de uso de datos temporales y el mapa. El volumen de sugerencias por sí solo tampoco acredita permiso de guardado.

## HERE y TomTom: límites de esta investigación

HERE distingue geocodificación y reverse ordinarios de geocodificación permanente; también deja fuera del paquete consultado autosuggest y autocomplete. Esto está publicado por HERE en su oferta de AWS. No se verificó una tarifa actual directa y aplicable al caso completo de Maia, por lo que no se presenta una cifra de blogs como cotización. Solicitar precio de almacenamiento permanente, visualización pública de inventario y mezcla con mapa OSM. [Oferta de HERE](https://aws.amazon.com/marketplace/pp/prodview-2ycujvbhl27am).

TomTom publica hoy cuotas mensuales por API y recomienda Places Search para proyectos nuevos, con transición hacia Orbis. Su antigua cifra de 2,500 llamadas diarias no debe trasladarse a una estimación nueva. La página de términos accesible no expuso su texto contractual completo; falta establecer persistencia y combinación de mapas. Sus cuotas gratuitas de búsqueda pueden servir para una comparación autorizada, pero no resuelven por sí solas el almacenamiento permanente. [Precios y transición](https://docs.tomtom.com/pricing), [entrada de términos](https://docs.tomtom.com/legal/terms-and-conditions).

## Prueba propuesta, todavía no realizada

Comparar Geoapify y LocationIQ con un conjunto autorizado de 30–50 direcciones conocidas: Guadalajara, Zapopan, Tlaquepaque, Tonalá, Tlajomulco, nuevos fraccionamientos, nombres repetidos, números interiores y casos rurales. Medir si la dirección correcta aparece entre las cinco primeras sugerencias, si identifica número exterior, porcentaje de municipio/colonia/estado completos, error del punto respecto a referencia conocida, latencia p50/p95 y llamadas reales por formulario. Registrar datos faltantes y las correcciones humanas. No premiar un proveedor que invente una colonia o marque el centro de una calle como edificio exacto.

La recomendación actual es documental y reversible: conservar Leaflet, probar primero esos dos geocodificadores y elegir por calidad local, licencias y coste del pico diario. No se eligió un proveedor ni se cambió el sistema.
