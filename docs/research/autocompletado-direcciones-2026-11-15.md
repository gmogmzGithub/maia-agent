# Autocompletado y ubicación de inmuebles en Maia

Investigación del 15 de noviembre de 2026. Google elegido por Guillermo para BETA y RC. La integración técnica se implementó posteriormente en esta misma sesión; claves y validación real siguen pendientes. Ver [activación y comportamiento implementado](../testing/google-ubicacion-beta.md).

## Decisiones confirmadas tras la investigación

Guillermo aceptó Q1–Q4: permitir consultas de dirección al proveedor elegido con información al usuario y datos mínimos; presupuesto inicial de $10 USD/mes con control de consumo y alternativa manual; captura manual cuando no haya coincidencia; ocultar coordenadas del recorrido normal. Eligió Google directamente para BETA y RC, en lugar de comparar primero Geoapify y LocationIQ. Espera menos de «1,000 créditos mensuales»; para dimensionar se propone interpretar conservadoramente 1,000 formularios mensuales, distinguiendo que cada uno genera varias solicitudes y que Google mide cuotas por SKU, no una bolsa común de créditos.

Guillermo aceptó Q5: usar también Google Maps en captación y fichas que presenten contenido de Places normal. Debe resolverse el tratamiento de dirección declarada, componentes del proveedor, identificador y coordenadas antes de persistir resultados. Ver [decisión de proveedor](../adr/0001-google-ubicacion-beta-rc.md).

Guillermo aceptó Q6: terrenos o ranchos sin calle, número o colonia pueden continuar con estado/municipio, referencia escrita y punto en el mapa, sujetos a revisión del equipo. No inventar componentes ni exigir una sugerencia incorrecta. Esta alternativa requiere ajustar la validación actual que exige colonia y dirección a todas las captaciones.

## Seguimiento: permanencia de datos con Google

La [guía oficial Locator Plus](https://developers.google.com/maps/architecture/store-locator/) describe dirección propia, identificador persistente y coordenadas guardadas con actualización al menos cada 30 días. Esto permite diseñar una caché separada del registro comercial, sin afirmar que Google permite conservación indefinida de cualquier resultado.

La auditoría encontró que hoy la información de ubicación se copia a captación, propiedad, contrato aceptado, adjunto del aviso, almacenamiento de sesión y fichas de conversaciones. Esas copias no tienen caducidad. Por tanto, añadir un TTL a una sola tabla no bastaría: resultados temporales Google deben quedar fuera de snapshots comerciales, contratos, correos e historial permanente, y no modificar revisiones comerciales al refrescarse. Ver [auditoría de copias](2026-11-15-current-location-and-osm.md).

No se encontró permiso expreso para que mover o confirmar el pin convierta sus coordenadas en contenido de conservación ilimitada. Tampoco para aplicar automáticamente la excepción de dirección seleccionada a todos los componentes inferidos y sus usos públicos. No hay una estrategia de retención completamente aprobada ni código Google implementado. La preservación del punto corregido por el propietario debe resolverse sin reemplazarlo silenciosamente por una nueva geocodificación.

**Q7 aceptada por Guillermo:** separar datos comerciales duraderos y resultados Google temporales, con refresco antes de 30 días y sin cambios al contrato aceptado. Esa aprobación no sustituye la comprobación del tratamiento del pin corregido y de cada campo que vaya a publicarse. La siguiente etapa se describe en el [plan de integración](../design/google-ubicacion-incremento-6.md).

## Recomendación inicial de la investigación

Conservar Leaflet y evaluar un geocodificador que permita persistir el resultado elegido y usarlo en nuestro inventario. Probar primero Geoapify y LocationIQ; considerar Amazon Location si se prefiere pago por uso con almacenamiento explícito. Elegir por precisión local medida y condiciones de uso, no por familiaridad de marca. Google puede ofrecer la experiencia, pero su combinación de mapa, datos persistentes y catálogo público necesita resolver restricciones específicas antes de integrarlo. No hay evidencia suficiente para afirmar qué API usa Inmuebles24.

## Qué falta hoy

El formulario actual recoge la dirección manualmente y Leaflet muestra el mapa OSM. No hay búsqueda de direcciones ni autollenado administrativo. El marcador inicial de Guadalajara se muestra incluso sin coordenadas guardadas; no es un resultado encontrado. Al integrar búsqueda habrá que ocultar ese marcador inicial y ajustar el zoom tras la selección. Estado/municipio/colonia deben normalizarse sin confundir municipio con localidad o ciudad. [Auditoría de implementación y fuentes](2026-11-15-current-location-and-osm.md).

La experiencia solicitada comprende tres operaciones: sugerir direcciones mientras se escribe, recuperar sus componentes y coordenadas, y pedir al propietario confirmar/corregir campos y punto. Cambiar de mapa no añade automáticamente esas funciones. Una sugerencia de dirección puede ser interpolada o estar incompleta; no certifica existencia física, acceso, identidad ni titularidad.

## Opciones y costes

Hipótesis comparativa: 100, 1,000 o 10,000 trámites mensuales; ocho consultas después de la espera entre pulsaciones y una selección por trámite. USD sin impuestos. No se incluyen abandonos, visitas públicas al catálogo, cambios posteriores, tráfico abusivo, servidor ni servicios adicionales. Los límites gratuitos se comparten con los demás consumos del mismo plan/cuenta. Los detalles de cálculos, fuentes y restricciones están en las notas enlazadas.

| Alternativa | Coste a 100 / 1,000 / 10,000 trámites | Condición decisiva |
|---|---|---|
| Geoapify | $0 / $0 / $0, condicionado al pico diario | 3,000 créditos/día y 5 req/s. Ocho sugerencias con componentes bastan: 8N llamadas. Uso comercial con atribución según precios; aclarar la tensión con términos antiguos antes de lanzamiento. Pago API 10 desde $59/mes. |
| LocationIQ | $0 / $0 / $0, condicionado al pico diario | 5,000 solicitudes/día, 2/s y 60/min. Ocho llamadas con selección local. Free requiere enlace visible. Developer $100/mes; Maps Lite $45 no incluye geocodificación. |
| Amazon Location | $0.56 / $5.60 / $56.00 | Ocho Autocomplete Label + un GetPlace con Storage por trámite; sin descontar promociones temporales. Precios us-east-1. |
| Google estándar | $0 / $0 / $198.10 | Ocho Autocomplete + Details Essentials y una carga de mapa por trámite, con cuotas gratuitas disponibles. No es una propuesta autorizada para guardar todos los datos ni usarlos en OSM. |
| Mapbox Geocoding permanente | $4 / $40 / $400 como presupuesto conservador | Ocho consultas permanentes a $5/1,000; mapas aparte. Su documentación exige mapa Mapbox. No confundir con Search Box temporal ni con el precio de resultados temporales. |

Fuentes: [Geoapify precios](https://www.geoapify.com/pricing/), [LocationIQ precios](https://locationiq.com/pricing), [catálogo oficial AWS us-east-1](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonLocationService/current/us-east-1/index.json), [precios Google](https://developers.google.com/maps/billing-and-pricing/pricing), [Geocoding Mapbox](https://docs.mapbox.com/api/search/geocoding/).

**Las cuotas diarias no se acumulan como bolsa mensual.** Por ejemplo, 1,000 trámites concentrados en un día consumen aproximadamente 8,000 consultas, por encima de los dos planes gratuitos. En cambio, 1,000 distribuidos en 30 días promedian unas 267 diarias. Sumar una búsqueda inversa por selección elevaría esos números a 9N; no es obligatoria para todos los proveedores.

La cifra Google no incluye los mapas que carguen los visitantes de las fichas públicas. Una BETA pequeña puede entrar en cuotas gratuitas, pero los mapas públicos y formularios abandonados se presupuestan separadamente. AWS tiene promociones para clientes elegibles; no se aplicaron porque su gratuidad Core no equivale al resultado Stored que conservaríamos.

## Condiciones que importan más que el precio inicial

**Geoapify:** documenta almacenamiento sin límite temporal, condicionado a las atribuciones de datos. El plan Free declara uso comercial/producción; sus términos antiguos contienen otra redacción sobre producción, por lo que conviene confirmar las condiciones aceptadas. [Datos y almacenamiento](https://www.geoapify.com/geocoding-api/), [términos](https://www.geoapify.com/terms-and-conditions/).

**LocationIQ:** su FAQ distingue conservar los datos de una respuesta indefinidamente de cachear pares petición/respuesta, limitado a 48 horas en Free. Guardar la ubicación elegida en una propiedad no equivale a construir una caché perpetua de todas las búsquedas. Respetar atribución y enlace del plan. [FAQ y planes](https://locationiq.com/pricing).

**AWS:** sugerencias temporales y resultado seleccionado almacenado son llamadas diferentes. `GetPlace` debe usar `IntendedUse: Storage`, que activa el nivel de precio Stored. Hay atribución y condiciones del proveedor de datos; confirmar uso público de los campos elegidos antes del lanzamiento. [Uso previsto](https://docs.aws.amazon.com/location/latest/developerguide/places-intended-use.html), [términos §82](https://aws.amazon.com/service-terms/).

**Google:** Places normal restringe mapas no Google y la conservación del contenido. Existen excepciones para dirección seleccionada por el propio usuario, caché aislada para ciertas operaciones y Places UI Kit. Ninguna se debe generalizar a coordenadas guardadas durante años y compartidas en CRM/catálogo. UI Kit permite mapas no Google, pero no se comprobó que entregue todos los componentes administrativos necesarios. [Políticas Places](https://developers.google.com/maps/documentation/places/web-service/policies), [términos específicos](https://cloud.google.com/maps-platform/terms/maps-service-terms).

**Mapbox:** su Geocoding permanente permite guardar, pero exige mapa Mapbox. Search Box es otro producto, con cobertura publicada de Estados Unidos, Canadá y Europa y resultados temporales; no debe proponerse como sustituto equivalente para México. [Geocoding](https://docs.mapbox.com/api/search/geocoding/), [Search Box](https://docs.mapbox.com/api/search/search-box/).

**Nominatim público:** queda descartado para este autocomplete. La política prohíbe esa modalidad, limita el conjunto de la aplicación a 1 req/s y pide no enviar información personal/confidencial. No confundir esa instancia pública con contratar un servicio basado en OSM o alojar uno propio. [Política oficial](https://operations.osmfoundation.org/policies/nominatim/).

**Propio con Photon/Pelias:** posible, pero requiere importar y actualizar fuentes, operar índices, respaldar y supervisar el servicio. No resuelve numeraciones inexistentes en los datos. Las referencias de VM de $24–96/mes no son un dimensionamiento probado para México. INEGI/SEPOMEX sirven como catálogos complementarios, no garantizan coordenadas por número exterior. [Investigación de OSM y catálogos oficiales](2026-11-15-current-location-and-osm.md).

## Precisión: lo que todavía no sabemos

No se ejecutó benchmark. La documentación no prueba que un proveedor encuentre con precisión una casa concreta en Guadalajara ni complete colonia o municipio sin errores. Una respuesta con latitud/longitud puede señalar un edificio, una interpolación de calle o el centro de una colonia. El punto privado del inmueble exige confirmación del propietario y revisión del equipo; el redondeo público es otra transformación independiente.

Propuesta: comparar primero Geoapify y LocationIQ con 60–100 casos autorizados, no con domicilios privados obtenidos sin permiso. Incluir vivienda, comercial, industrial, rural, calles homónimas, fraccionamientos nuevos y distintos estados. Medir candidato correcto top 1/top 5, cada componente administrativo, distancia al acceso real, porcentaje sin correcciones, latencia p95 y llamadas facturables por trámite, incluidos abandonos. Confirmar términos y origen de los datos antes de ejecutar la muestra.

La muestra no debe producir una base mezclada de respuestas con licencias incompatibles. Registrar métricas agregadas y conservar únicamente lo permitido por cada contrato. No añadir nombre, email, teléfono ni información del contrato a las consultas.

## Flujo propuesto para Maia

1. Campo principal «Busca la dirección de tu inmueble», español y México, con preferencia por ZMG sin excluir otros estados.
2. Mostrar hasta cinco candidatos, navegar con teclado y elegir uno.
3. Completar solo componentes presentes y coherentes. Mantener edición manual. No inventar colonia, CP, número ni fraccionamiento.
4. Colocar el punto y acercar el mapa. Pedir confirmar/corregir antes de continuar. No iniciar con una marca que parezca una dirección ya resuelta.
5. Si cambia la dirección escrita, invalidar la resolución anterior hasta reconfirmarla. Una respuesta tardía no reemplaza una corrección manual. Mover el pin no reescribe silenciosamente la dirección.
6. Conservar captura manual si no hay resultados o falla el proveedor; evaluar por separado cómo atender predios sin colonia o número.
7. Mantener privadas la dirección y coordenadas exactas; aplicar la autorización de publicación del equipo independientemente de la búsqueda. Mostrar atribución del proveedor conforme a su contrato.
8. Autorizar y limitar las consultas desde backend; claves restringidas, mínimo de caracteres, espera entre pulsaciones y cancelación de búsquedas anteriores. Evitar direcciones completas en logs y analítica. Los avisos de presupuesto no son un límite de gasto: se necesita un corte de consumo con alternativa manual.

## Árbol de decisiones y entrevista

Ya acordado: captación de inmuebles de México, base operativa ZMG y excepciones fuera de zona; vivienda/comercial/industrial/rural; ubicación privada por defecto; publicar ubicación exacta requiere autorización del equipo. El cambio solicitado es sugerir dirección, autollenar y aproximar el punto antes de la corrección humana.

Primera ronda, recomendaciones aceptadas por Guillermo:

- **Q1, transmisión:** cambiar la decisión anterior de no enviar direcciones privadas a terceros para permitir consultas mínimas al proveedor que se elija. Recomendación: sí, explicarlo en la interfaz y limitar los datos.
- **Q2, presupuesto:** elegir tope mensual para el servicio. Propuesta inicial: $10 USD para BETA con corte y alternativa manual; evaluar pagos mayores solo si la calidad o uso medido lo justifica.
- **Q3, sin coincidencia:** decidir si puede continuarse con dirección y punto manuales cuando el buscador no responde o no encuentra el predio. Recomendación: sí, especialmente por cobertura rural y propiedades nuevas.
- **Q4, coordenadas:** decidir si latitud/longitud salen del recorrido normal y el propietario interactúa con el mapa. Recomendación: sí; conservarlas solo como información avanzada cuando haga falta.

Proveedor elegido: Google para BETA y RC, incluido el mapa de captación y las fichas que presenten sus resultados. Siguen pendientes criterios de aceptación de cobertura local, persistencia por contrato, tratamiento de colonia/número ausentes y alcance concreto de implementación en el incremento 6. El ADR no da por resueltas las restricciones de almacenamiento.

## Notas de respaldo

- [Google: productos, costes y excepciones](2026-11-15-google-address-autocomplete.md).
- [Geoapify, LocationIQ, Mapbox, HERE y TomTom](2026-11-15-address-providers.md).
- [Amazon Location y cálculo de tarifas oficiales](2026-11-15-amazon-location.md).
- [Implementación actual, OSM, autoalojamiento y benchmark](2026-11-15-current-location-and-osm.md).
