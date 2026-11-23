# EasyBroker: alcance de cuenta, varias cuentas y API de partners

Investigación documental del 22 de noviembre de 2026. Solo fuentes oficiales. No se conectó ninguna cuenta real, no se usaron claves privadas y no se hicieron escrituras externas. Guillermo aún no tiene cuenta y prevé tenerla antes de RC. Las pruebas del sandbox se documentan por separado; sus resultados no acreditan permisos reales de una cuenta futura.

## Conclusión

La API ordinaria consulta el inventario de la **cuenta/organización autenticada por una clave**, no un conjunto de propiedades descubierto mediante un email. La autenticación documenta una clave única por cuenta, obtenida por un administrador. El listado de propiedades declara alcance de organización; también existe un listado de sus usuarios activos. [Autenticación](https://dev.easybroker.com/docs/autenticaci%C3%B3n), [propiedades](https://dev.easybroker.com/reference/get_properties), [usuarios](https://dev.easybroker.com/reference/get_users).

Por tanto, diseñar varias conexiones, una por cuenta autorizada y su clave, es una **propuesta técnica de Maia**, no un endpoint agregado prometido por EasyBroker. No se encontró autorización por email ni un mecanismo ordinario para leer cualquier cuenta sin que su administrador proporcione acceso. Varios asesores de una misma organización no deben confundirse con varias organizaciones. Estas distinciones se infieren del alcance anterior y deberán comprobarse con las cuentas reales antes de RC.

## Capacidades comprobadas de la API ordinaria

- La cuenta real requiere plan de pago y clave. Existe un ambiente de pruebas con datos ficticios, utilizable sin abrir cuenta. La documentación fija 20 solicitudes/segundo y exige consumir la API desde el servidor. [Introducción](https://dev.easybroker.com/docs/api-de-easybroker).
- `GET /properties` ofrece paginación de hasta 50 propiedades, filtros de estado y fechas de actualización. Los estados documentados incluyen `published`, `not_published`, `reserved`, `sold`, `rented`, `suspended`, `flagged` y `disapproved`. El filtro no documenta búsqueda por email ni selección de organización ajena. [Referencia y OpenAPI de propiedades](https://dev.easybroker.com/reference/get_properties).
- `GET /properties/{property_id}` consulta el detalle. La API también permite crear y actualizar propiedades; crear una propiedad publicada puede enviarla a los portales activos. Estas escrituras son capacidades disponibles, **no alcance aprobado de la primera integración**. [Guía de propiedades](https://dev.easybroker.com/docs/propiedades).
- `GET /listing_statuses` ordinario consulta estados de la organización, hasta 100 por página. Su alcance y contrato no deben confundirse con `/integration_partners/listing_statuses`. [Estados ordinarios](https://dev.easybroker.com/reference/get_listing-statuses).

## Colaboraciones y Bolsa Inmobiliaria

La API ordinaria tiene `GET /collaborations`, descrito como listado de colaboraciones de la organización. Eso no demuestra que `/properties` incluya automáticamente todo su inventario ni la Bolsa Inmobiliaria completa. [Referencia de colaboraciones](https://dev.easybroker.com/reference/get_collaborations).

La ayuda explica que los anuncios compartidos de colaboradores pueden mostrarse en el sitio web EasyBroker al habilitarlos, pero **no se agregan al inventario dentro del CRM**. No extrapolar esa capacidad del sitio hospedado a una autorización API general. Queda pendiente confirmar con EasyBroker el mecanismo y los derechos aplicables si después se quieren propiedades de colaboradores. [Qué son las colaboraciones](https://ayuda.easybroker.com/article/95-que-son-las-colaboraciones).

## API de aplicación/partner: otro producto de integración

La guía correspondiente se dirige expresamente a aplicaciones partners y remite al cliente ordinario a la API de su cuenta. Usa `/v1/integration_partners`, clave entregada a la integración y país activo. Las propiedades son las enviadas al portal, relacionadas mediante `agency_id` y, cuando aplica, `agent_id`; no constituyen acceso irrestricto a toda la bolsa. [Introducción partners](https://dev.easybroker.com/docs/introducci%C3%B3n), [detalle partners](https://dev.easybroker.com/docs/properties-2).

El proceso exige enlazar/desenlazar cuentas, publicar/actualizar/dar de baja, informar estatus y enviar solicitudes de contacto, seguido de pruebas y aprobación de EasyBroker. La recomendación de sondeo cada 15–30 minutos de esa guía corresponde a ese flujo; puede inspirar Maia, pero no prueba que el inventario ordinario se entregue mediante callbacks o sin consultas. [Introducción partners](https://dev.easybroker.com/docs/introducci%C3%B3n).

La política publicada para añadir portales excluye a los que participan en transacciones obteniendo comisiones de compra/renta; para portales elegibles incluye un pago único de USD 5,000 por integración/certificación y revisión. **No es el precio de usar la API ordinaria de una cuenta.** Maia está diseñada para una inmobiliaria: no asumir elegibilidad ni recomendar esta vía como requisito para importar varias cuentas autorizadas. [Política de portales](https://ayuda.easybroker.com/article/530-partnerships).

## Evidencia ejecutada en sandbox

El agente principal realizó tres consultas GET al ambiente oficial de pruebas con la clave pública de su documentación, sin mutaciones: listado con `page=1&limit=2`, detalle por `public_id` y listado filtrado con `search[statuses][]=published`. Las tres devolvieron HTTP 200. El listado incluyó `content` y `pagination` con 1,608 registros declarados; el detalle contenía 11 imágenes, operaciones, ubicación, agente y descripción privada. La muestra de listado/detalle no incluyó campo `status`: que el filtro funcione no demuestra que cada detalle exponga ese campo. Evidencia local de esta ejecución: `/tmp/maia-easybroker-sandbox-proof.json`.

Esta ejecución comprueba lectura y estructura de datos ficticios. No valida el plan contratado, alcance entre cuentas, inventario de colaboradores, derechos de uso ni las credenciales futuras de Guillermo. El ambiente se identifica en la [introducción oficial](https://dev.easybroker.com/docs/api-de-easybroker).

Después se amplió y repitió la prueba con cuatro GET: los tres anteriores y `/listing_statuses?page=1&limit=2`, todos HTTP 200. Este cuarto endpoint devolvió `public_id`, `status` y `updated_at`, con estados `not_published` y `published` en la muestra. Esto acredita un recurso ordinario específico para consultar estados, separado del detalle y de la API partner; no acredita aún que notifique eliminaciones definitivas ni todas las reglas de permisos. La evidencia local anterior se actualizó con esta ejecución.

## Consecuencias propuestas para el diseño

1. Conservar por separado cuenta/conexión de origen, identificador EasyBroker y registro local. El email puede ser descriptivo, nunca llave de autorización o identidad de propiedad.
2. Importar automáticamente bajo cada cuenta configurada, con límites por conexión, reintentos y revisión del progreso. No conectar cuentas buscando correos.
3. Separar el estado externo de publicación del control local de exposición en Maia. Un asesor debe poder ocultar localmente sin que el siguiente sondeo la publique otra vez. Ocultar en Maia no implica escribir en EasyBroker.
4. Una baja externa debe impedir seguir ofreciendo una propiedad, conservando historial; un estado externo vendido/rentado no debe inventar precio final ni confirmar un cierre propio.
5. Confirmar con Guillermo si despublicar significa solo ocultar en Maia o cambiar también EasyBroker. La segunda opción ampliaría las escrituras externas que quedaron fuera de Q1.

Estas son propuestas pendientes de diseño. No se ha implementado una importación ni se ha determinado todavía frecuencia, manejo de fallos, derechos de fotos, alcance de colaboradores o política de datos privados. La cuenta de pago y sus capacidades reales deberán probarse antes de declarar RC lista.

## Comprobación posterior: formatos especiales

El [esquema oficial de propiedades](https://dev.easybroker.com/reference/post_properties) admite importes totales, por metro cuadrado o por hectárea y una variante de renta temporal. No se recuperó el detalle suficiente para fijar los valores exactos de periodicidad temporal. No convertir esos importes a total o mensualidad por suposición. El mismo esquema documenta imágenes mediante URL firmada: conservar parámetros y actualizar enlaces cuando cambien, sin prometer disponibilidad permanente.

Maia admite actualmente venta/renta y MXN/USD en `backend/datalayer/schemas.py`, sin unidad comercial del precio. El catálogo externo se obtiene de [tipos de propiedad](https://dev.easybroker.com/reference/get_property-types) y debe corresponderse con el catálogo propio. No se identificó todavía un tipo concreto incompatible ni un listado cerrado de monedas externas; se diseña una política de excepción sin afirmar que la futura cuenta contendrá esos casos. Las decisiones posteriores de frecuencia, privacidad y conservación están en el [diseño vigente](../design/siguiente-etapa-easybroker-cuentas-contratos-gui-rc.md), que prevalece sobre las propuestas iniciales de este informe.
