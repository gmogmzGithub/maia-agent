# Google para autocompletar la ubicación de una propiedad

Investigación del 15 de noviembre de 2026. Fuentes oficiales consultadas en esa fecha. No se enviaron direcciones de Guillermo a una API ni se probaron credenciales, cobertura local o precisión de puerta. Documento de investigación, no decisión de implementación ni dictamen jurídico.

## Conclusión para Maia

Google puede implementar la experiencia solicitada: sugerencias mientras se escribe, selección de dirección, obtención de componentes y coordenadas, y ajuste del marcador. El precio de una BETA pequeña puede ser cero dentro de las cuotas por SKU. La dificultad principal para nuestro diseño es la licencia de los resultados que queremos conservar y mostrar en un inventario público, no el coste inicial.

No recomiendo decidir «Google Places + guardar todo para siempre + Leaflet» sin resolver esas condiciones. Tampoco es correcto afirmar que todo Google obliga siempre a usar un mapa Google: Places UI Kit tiene una excepción expresa. Esa alternativa, sin embargo, no ofrece documentados todos los componentes que necesitamos para autollenar el formulario.

## Qué API resuelve cada parte

Autocomplete (New) acepta el texto parcial y devuelve sugerencias identificables. Se puede restringir a México con `includedRegionCodes`, seleccionar español y sesgar hacia Guadalajara con `locationBias`. Un sesgo permite otros resultados; una restricción territorial los excluye. Eso permite priorizar la zona base sin impedir captaciones de otros estados. [Autocomplete (New)](https://developers.google.com/maps/documentation/places/web-service/place-autocomplete).

Tras elegir una sugerencia, Place Details (New) puede solicitar `id,addressComponents,formattedAddress,location,viewport`. Los componentes, dirección, coordenadas y viewport pertenecen a Essentials. No hace falta otra consulta Geocoding para colocar ese resultado en el mapa. `displayName` pertenece a Pro y no se necesita para este caso. El FieldMask es obligatorio; no usar `*`. [Place Details (New)](https://developers.google.com/maps/documentation/places/web-service/place-details).

Google declara Geocoding disponible en México, pero esa cobertura nacional no prueba la precisión de cada finca de Guadalajara, fraccionamiento nuevo o rancho. [Cobertura oficial](https://developers.google.com/maps/coverage).

Los componentes pueden faltar o cambiar de orden. En Geocoding, `ROOFTOP`, `RANGE_INTERPOLATED`, `GEOMETRIC_CENTER` y `APPROXIMATE` expresan niveles distintos de localización. No equivalen a validar propiedad, acceso al inmueble ni linderos. El formulario debe permitir confirmar/corregir los campos y mover el marcador; no inventar colonia o subdivisión ausentes. [Respuesta de Geocoding](https://developers.google.com/maps/documentation/geocoding/guides-v3/requests-geocoding).

Propuesta de evaluación, no implementada: distinguir calle/número, estado, municipio, localidad/ciudad, colonia, fraccionamiento, código postal y punto confirmado. La equivalencia de componentes de Google con términos mexicanos requiere probarse con casos reales autorizados; no tomar `locality` como municipio en todos los casos.

## Licencia: distinguir producto y procedencia del dato

Para una cuenta facturada fuera del EEE, Places API y Geocoding prohíben combinar su contenido con un mapa no Google. Places permite caché de coordenadas por 30 días; los identificadores tienen excepción de caché. Places UI Kit sí autoriza mapas no Google, pero conserva restricciones de almacenamiento. Geocoding añade una excepción de caché indefinida, limitada a la funcionalidad directa del usuario originador, aislada por usuario y sin sustituir nuevas llamadas. No autoriza por sí sola reutilizar esos datos para otros usuarios de nuestro catálogo. La dirección de facturación determina el régimen EEE, no el país de la propiedad. [Términos específicos, apartados A.3, B.6, B.14 y B.15](https://cloud.google.com/maps-platform/terms/maps-service-terms).

Hay otra excepción importante: la dirección callejera que el propio usuario selecciona mediante Autocomplete puede quedar fuera de las restricciones de contenido para su transacción concreta si la habría aportado completa y correctamente sin autocompletado. No cubre la lista de sugerencias, otros servicios, POI ni el resto del contenido, incluidas coordenadas. No debe interpretarse que arrastrar mínimamente un marcador convierte todos los datos Google en datos independientes. Se exige atribución Google Maps y términos/política de privacidad públicos. [Políticas Places, especialmente “Autocomplete for end user addresses”](https://developers.google.com/maps/documentation/places/web-service/policies).

**Inferencia para Maia:** una captación con contrato de seis meses, revisiones CRM y ficha pública no cabe automáticamente en una excepción de transacción privada del propietario. Hay que confirmar qué campos pueden persistirse, si se publicarán, por cuánto tiempo y con qué procedencia. Separar en el modelo datos declarados por propietario, resultados del proveedor y punto confirmado ayuda a aplicar reglas, pero no crea derechos que el contrato del proveedor no conceda.

Además de las condiciones de contenido, Google recibe búsquedas y datos técnicos durante el uso. El diseño debe informar al propietario de que el autocompletado consulta a un proveedor externo y evitar añadir nombre, email o teléfono a esas consultas. [Términos generales, apartado 4.4](https://cloud.google.com/maps-platform/terms).

## La alternativa Google Places UI Kit

`BasicPlaceAutocompleteElement` devuelve un ID y limpia la entrada tras seleccionar. Usa su SKU por sesión y no el SKU de Autocomplete normal. [Basic Autocomplete](https://developers.google.com/maps/documentation/javascript/places-ui-kit/basic-autocomplete).

Los elementos Details del UI Kit exponen públicamente un `place` con ID, ubicación y viewport. La referencia no documenta que esta propiedad entregue `addressComponents` para rellenar nuestros campos. Llamar después al Place Details API normal añade las condiciones y facturación de ese servicio; no hereda automáticamente la excepción del UI Kit. No considero probada su equivalencia completa con el flujo de Maia. [Referencia PlaceDetailsElement.place](https://developers.google.com/maps/documentation/javascript/reference/places-widget#PlaceDetailsElement.place).

La facturación diferencia una sesión Basic Autocomplete de una solicitud a Details/Search del UI Kit. [Definición de eventos facturables](https://developers.google.com/maps/billing-and-pricing/sku-details/places).

## Precios globales y escenarios

USD, sin impuestos, tipo de cambio ni promociones. Primer tramo pagado hasta 100.000 eventos mensuales; los consumos de proyectos ligados a la misma cuenta de facturación se agregan por SKU. No es el antiguo crédito mensual general de $200.

| SKU | Uso mensual gratuito | USD por 1.000 eventos posteriores |
|---|---:|---:|
| Autocomplete Requests | 10.000 | 2,83 |
| Place Details Essentials | 10.000 | 5,00 |
| Geocoding | 10.000 | 5,00 |
| Dynamic Maps | 10.000 | 7,00 |
| Places UI Kit Autocomplete por sesión | 10.000 | 10,00 |
| Places UI Kit Query | 10.000 | 1,00 |

[Lista oficial de precios](https://developers.google.com/maps/billing-and-pricing/pricing).

En sesiones normales cerradas con Details Essentials se facturan las primeras 12 solicitudes Autocomplete; desde la 13 no cobran, más la consulta Details. Abandonar una sesión deja sus solicitudes facturables. Terminar con IDs Only no elimina ese cargo. Pedir campos no Essentials puede cambiar la terminación a una categoría más costosa; no asumir que pedir Pro mantiene el mismo cálculo. [Reglas de sesiones](https://developers.google.com/maps/documentation/places/web-service/session-pricing).

**Supuestos propios del cálculo:** una sesión completada por formulario, ocho consultas Autocomplete después del debounce y una selección Details Essentials; sin abandonos, cambios de dirección, reintentos, búsquedas públicas ni otras aplicaciones consumiendo las cuotas. Una carga Dynamic Maps por formulario cuando se incluye mapa Google. Ninguna consulta adicional Geocoding.

| Formularios/mes | Autocomplete Requests | Details Essentials | Costo Autocomplete | Costo Details | Costo mapa del formulario | Total estimado |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 800 | 100 | $0 | $0 | $0 | $0 |
| 1.000 | 8.000 | 1.000 | $0 | $0 | $0 | $0 |
| 10.000 | 80.000 | 10.000 | $198,10 | $0 | $0 | $198,10 |

Cálculo propio para 10.000: `(80.000 - 10.000) / 1.000 × 2,83 = 198,10`. Los otros dos SKUs no superan cada uno su cuota. No equivale a que 10.000 inmuebles publicados garanticen ese coste: cuentan todos los intentos, abandonos y reaperturas, no solo propiedades terminadas. Las visitas del catálogo se cuentan aparte si cargan mapas Google.

La alternativa UI Kit, suponiendo exactamente una sesión facturable y una consulta Details por formulario, también queda en $0 en los tres tamaños anteriores, pero eso no prueba que ofrezca todos los campos ni resuelve las restricciones de retención. Cada combinación de productos debe estimarse con su propia unidad facturable.

## Controles de coste y prueba antes de decidir

Google requiere facturación habilitada para Places aunque el consumo entre en la cuota gratuita. Restringir claves, medir SKUs efectivos y solicitar solo los campos necesarios. [Uso y facturación](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing). Las alertas presupuestarias avisan; los límites de cuota son el mecanismo para cortar consumo. El estado de facturación puede tener retraso. [Control de costes](https://developers.google.com/maps/billing-and-pricing/manage-costs).

Propuesta de prueba comparativa, pendiente de autorización/configuración:

1. Usar 30–50 direcciones autorizadas: municipios de la ZMG, calles homónimas, acentos, colonias nuevas, condominios, locales/industrias, propiedades rurales y casos fuera de Jalisco.
2. Medir sugerencia útil entre las primeras cinco, componentes completos/correctos, distancia al punto de referencia, número de correcciones, latencia y consumo facturable.
3. Probar que la escritura manual y el marcador siguen disponibles cuando no hay resultados, falta colonia, se agota cuota o falla la red.
4. Determinar separadamente el origen y permiso de persistencia de cada campo que llegará al CRM y al catálogo. No enviar consultas reales a proveedores durante la investigación documental.
5. Resolver las condiciones de Google antes de elegirlo para almacenar coordenadas permanentes de un inventario público.

No hay evidencia en esta investigación de qué proveedor usa Inmuebles24. Su apariencia no identifica una API ni demuestra licencia o cobertura de otro producto.

## Seguimiento: Google elegido para BETA/RC y persistencia del inventario

Guillermo eligió Google para BETA/RC, incluido sustituir el mapa. Esa elección elimina el conflicto de mostrar resultados Places en Leaflet, pero no elimina las condiciones de almacenamiento. Lo siguiente es una propuesta de diseño, no código implementado ni declaración de que cualquier dato confirmado por el usuario deje de estar sujeto a licencia.

### Evidencia oficial que permite un diseño operativo

Google documenta expresamente un localizador con base de datos propia: conservar dirección propia e identificador, geocodificar en servidor, guardar coordenadas y refrescarlas al menos cada 30 días. Es una base oficial más clara para el inventario público que intentar ampliar la excepción de Geocoding aislada por usuario. [Locator Plus, “Getting place IDs” y “Geocoding your locations”](https://developers.google.com/maps/architecture/store-locator/).

El servicio web se propone también para geocodificar un conjunto de direcciones de un sitio inmobiliario, respetando las condiciones de caché. Google ofrece soluciones inmobiliarias con mapas y datos propios. Estos ejemplos apoyan la viabilidad del uso inmobiliario; no conceden una excepción adicional de retención. [Uso de servicios web](https://developers.google.com/maps/optimize-web-services), [soluciones inmobiliarias](https://mapsplatform.google.com/solutions/real-estate/).

### Dirección de una propiedad y campos administrativos

La excepción ya citada para dirección seleccionada por el propio usuario no enumera contratos de captación, CRM ni anuncios públicos. **Inferencia plausible, no confirmación contractual:** el propietario que conoce y aporta la dirección completa de su inmueble se aproxima al supuesto de dirección que habría proporcionado sin ayuda, para su operación concreta. No debe asumirse que toda búsqueda de inmuebles o cualquier dirección de terceros cumpla ese supuesto.

Google muestra oficialmente cómo rellenar un formulario mediante `addressComponents`, con variaciones regionales. Eso acredita el uso técnico de los componentes para autollenado. No aclara expresamente si cada colonia, municipio o fraccionamiento inferido puede guardarse permanentemente como dirección seleccionada ni si ese permiso se extiende a todos los usos públicos posteriores. [Ejemplo oficial de formulario de dirección](https://developers.google.com/maps/documentation/javascript/examples/places-autocomplete-addressform).

Propuesta conservadora: conservar por separado el texto y los campos que el propietario aporta por conocimiento propio, el identificador de la selección y los campos Google usados para ayudarle. No etiquetar automáticamente todos los componentes como propios después de una confirmación genérica. Resolver el alcance de la dirección seleccionada antes de depender de él para contratos inmutables o campos públicos permanentes.

### ¿Mover el pin produce coordenadas propias permanentes?

**No se encontró una autorización oficial expresa de retención indefinida para ese caso.** Maps JavaScript demuestra obtener `MapMouseEvent.latLng` de un clic. El ejemplo acredita la función técnica, no una excepción de licencia ni que `getPosition()` convierta el resultado en datos independientes. [Ejemplo oficial de evento de clic](https://developers.google.com/maps/documentation/javascript/examples/event-click-latlng).

Los términos generales definen contenido Google ampliamente y limitan crear contenido a partir de él. La definición de `Customer Data` encontrada en los términos específicos pertenece a Google Earth y no debe trasladarse a Maps JavaScript. No se propone obligar a arrastrar un metro el marcador ni añadir una casilla para eludir condiciones. Queda pendiente aclarar cómo conservar una corrección del pin a largo plazo cuando solo procede del mapa. [Términos generales, 3.2.3 y definiciones](https://cloud.google.com/maps-platform/terms), [términos específicos, apartado 8 de Google Earth](https://cloud.google.com/maps-platform/terms/maps-service-terms).

### Arquitectura conservadora propuesta

| Capa | Información | Tratamiento propuesto |
|---|---|---|
| Captación y contrato | Dirección y componentes aportados independientemente por propietario | Datos de negocio versionados; conservar autor, fecha y procedencia. Mantener el contrato estable. |
| Referencia Google | `place_id` | Persistir como referencia del inmueble; admitir que cambie o deje de resolver. |
| Caché geográfica | Coordenadas retornadas por Geocoding/Places, origen y fechas | Separada de `capture.data`, Property y contratos inmutables; TTL inferior a 30 días y reemplazo controlado. |
| Mapa CRM/propietario | Coordenadas exactas vigentes | Solo respuestas autorizadas. Si la caché venció, resolver de nuevo; si falla, no servir el dato vencido como actual. |
| Mapa público | Referencia geográfica pública autorizada | Solo mapa Google; jamás enviar dirección o `place_id` exactos ocultos al cliente cuando se promete ubicación aproximada. |
| Contrato y auditoría | ID de captación, dirección propia, revisión, aceptación | No incrustar coordenadas Google temporales en snapshots de seis meses, PDF, eventos ni cuerpos de correo. |
| Copias y archivos | Históricos, snapshots y respaldos de la caché | Excluir la caché de exportaciones permanentes y diseñar su purga. No basta con borrar solo la fila activa. |

La resolución bajo demanda de un ID permanente es el patrón documentado; los IDs pueden quedar obsoletos y Google recomienda refrescarlos después de 12 meses. La caché de coordenadas y la actualización de IDs son dos plazos distintos. [Guía de Place IDs](https://developers.google.com/maps/documentation/places/web-service/place-id).

Este diseño permite separar una actualización cartográfica de una modificación contractual: refrescar la ubicación técnica no debe cambiar silenciosamente la dirección aceptada, la revisión de captación ni el contrato. Un cambio material detectado requiere revisión humana; no reemplazar datos de negocio con una nueva respuesta Google.

### Límites que todavía hay que cerrar

1. **Dirección permanente:** confirmar qué campos se tratan como dirección aportada por propietario para su captación. El autollenado técnico por sí solo no resuelve la autorización para guardar todas las partes inferidas.
2. **Corrección exacta del pin:** no prometer retención indefinida de coordenadas del mapa sin una base expresa o una fuente independiente. La caché renovable resuelve la ubicación Google de referencia, pero no garantiza conservar para siempre una corrección manual distinta de esa referencia.
3. **Ubicación aproximada pública:** no se encontró guía oficial que autorice específicamente redondear coordenadas Places y tratarlas como datos propios. Puede separarse una ubicación pública por zona, basada en una zona declarada independientemente y resuelta con caché vigente; es una propuesta de producto que requiere aceptar su menor precisión. No enviar al navegador el ID ni el punto exactos y limitarse a ocultar visualmente el marcador.
4. **Snapshot contractual:** cualquier implementación que copie todo el JSON de ubicación a un acuerdo permanente debe separar primero los datos temporales Google. La aprobación de Google como proveedor no autoriza conservar esos resultados por seis meses.

El camino técnicamente más sencillo sin depender de retención indefinida es dirección propia + referencia persistente + caché renovable + mapas Google. Los puntos anteriores describen sus límites concretos; no requieren cambiar de proveedor para investigar o construir el resto del flujo.
