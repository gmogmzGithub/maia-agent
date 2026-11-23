# Registro de cierres: diseño técnico

## Corrección vigente: sesión y autoría · 22 de noviembre de 2026

Guillermo elimina el permiso adicional de cierres, también para administradores. Una cuenta activa del equipo con sesión CRM puede registrar y actualizar operaciones. Se retiran los controles de permisos y su endpoint; las antiguas tablas de autorización se conservan únicamente como datos históricos, sin condicionar acciones. Se mantiene la autenticación del equipo, CSRF, revisión del resumen y control de concurrencia.

Cada nueva revisión de operación y evento de propiedad/captación, además de las vinculaciones de inmuebles, conserva el identificador y una copia del correo del autor obtenidos de la sesión en el servidor. Un correo enviado por el cliente no decide la autoría. Cambiar después el correo de la cuenta no reescribe el historial. Los eventos previos conservan su identificador; no se inventa el correo que tenían entonces. La migración 0017 añade esos campos sin cambiar los datos anteriores. Esta decisión sustituye los requisitos anteriores de habilitación adicional.

Fecha: 22 de noviembre de 2026. Estado: diseño aprobado por Guillermo e implementado localmente; [validación](../testing/cierres-y-comparables.md). Traduce los acuerdos Q1–Q39 de [cierres y comparables](cierres-y-comparables.md).

## Separación de responsabilidades

| Registro | Responsabilidad | Compatibilidad |
| --- | --- | --- |
| Inmueble físico | Identidad estable del bien y vínculo entre sus operaciones. | Registro nuevo; no sustituye referencias públicas. |
| Oferta de comercialización | Oferta concreta de venta o renta, publicación y captación asociada. | Se conserva `Property`, sus claves, referencia, relaciones y URLs. |
| Cierre | Resultado real de una operación, características históricas y revisiones. | Registro nuevo privado, separado del precio solicitado. |

Un inmueble puede tener varias ofertas y cierres independientes. Una carga histórica puede crear solo inmueble y cierre, sin oferta, publicación ni cuenta de propietario. Compartir dirección no fusiona identidades. Las sugerencias de coincidencia de Q16/Q36 solo ayudan al equipo; no verifican características ni realizan vinculaciones automáticas.

## Modelo propuesto

Modelos implementados, sin renombrar modelos anteriores:

- `PhysicalProperty`: UUID estable, referencia interna y fechas de creación/modificación. La ubicación conocida puede ayudar a identificarlo, pero los hechos históricos pertenecen a cada revisión del cierre. `Property` incorpora una relación con esta identidad.
- `Closing`: UUID, inmueble, oferta opcional, origen actual/histórico, autor, fecha de creación, revisión vigente y número de versión. La oferta y su inmueble deben corresponder. Una vez confirmado, los cambios se realizan mediante acciones auditadas; no existe borrado ordinario.
- `ClosingRevision`: copia completa de los datos del cierre, número único por cierre, acción, estado, autor, fecha y motivo. La primera confirmación y todas las correcciones/anulaciones/reversiones conservan versiones anteriores. La revisión vigente es la fuente de lectura; no se reconstruye el pasado desde inventario o captación.
- Autorización explícita de cierres por usuario autenticado y eventos de concesión/revocación. Solo administradores pueden cambiarla. Acceso al CRM o ficha de asesor no bastan para confirmar. El administrador de Django debe pasar por las mismas reglas y no permitir editar/borrar directamente versiones confirmadas.
- `SearchIntent`, acotado a Q23: identidad de la búsqueda, prospecto, conversación de origen, inicio, requisitos propios y resolución opcional con cierre, autor y fecha. El ciclo de seguimiento identifica esta búsqueda. No habilita varios seguimientos abiertos por prospecto ni una administración nueva de búsquedas múltiples.
- `PhysicalPropertyLink`: vinculación humana de identidades con autor, fecha y motivo. Conserva los UUID originales y agrupa sus operaciones mediante una identidad canónica; no borra ni reescribe revisiones históricas.
- `OfferClosure`: vínculo único oferta/periodo/cierre y constancia de reapertura. `ClosingRequest` conserva el resultado de cada comando para reintentos idempotentes. `ClosingAuthorization` y sus eventos administran el permiso explícito y su auditoría.

Las referencias que sostienen el historial se protegen del borrado ordinario. No se fija aquí un plazo legal de conservación ni se aprueba guardar datos personales indefinidamente. Un procedimiento excepcional de privacidad o depuración requiere diseño propio y no se añade como botón de borrado de cierres.

### Datos de cada revisión

| Grupo | Datos |
| --- | --- |
| Operación | Venta/renta, estado, responsable comercial, usuario que confirma y fecha de confirmación. |
| Importe | Precio final base decimal, moneda MXN/USD. Venta total o renta mensual. Sin conversión. |
| Fecha real | Año, mes y día conocidos por separado en borrador; fecha completa válida para confirmar. |
| Identificación | Tipo/subtipo del catálogo actual e identificación urbana o rural histórica. |
| Zona | Estado, municipio, tipo de referencia local y nombre de colonia/barrio/localidad, consultables por separado. |
| Dirección urbana | Calle, número exterior, interior cuando corresponda y colonia. Se distingue interior no aplicable de interior desconocido. |
| Identificación rural | Localidad, predio/lote/parcela y referencia documental individualizante; acceso como complemento. |
| Superficies | Terreno, construcción y privativa en m², separadas, decimales y desconocidas como NULL. |
| Características | Recámaras, baños, medios baños, estacionamientos, antigüedad, conservación y amenidades aplicables. Desconocido se distingue de cero, ausencia o no aplicable. |
| Cargos | Estado de desglose desconocido/sin cargos/con detalle; lista de concepto, importe y moneda por cargo. |
| Vínculos y control | Comprador/arrendatario opcional, marca de prueba, referencia o notas opcionales. |

Operación, precio, moneda, fecha, zona, tipo y superficies son campos estructurados, no texto libre ni datos ocultos en notas. Cargos y características adicionales pueden usar JSON validado y versionado; no se crea un catálogo nuevo de características. Para el formulario se reutilizan las agrupaciones del catálogo actual, sin ampliar tipos.

Guardar un borrador admite campos pendientes y fechas parciales. Confirmar exige todos los mínimos Q12/Q17/Q21/Q22. Superficies y otras características desconocidas generan advertencias de ficha incompleta, sin inventar valores ni bloquear un cierre válido. No se generan valoraciones, puntuaciones de calidad ni certificados de veracidad.

No se almacena un precio por m² introducido independientemente del precio y la superficie. Los datos permiten derivarlo después con denominador, moneda y periodicidad identificados. Esta entrega no incluye buscador de comparables ni calculadora de valuación. Un índice de precio total/m² no separa valor del suelo y de la edificación.

### Ubicación y Google

Se reutilizan `LocationFields`, la sesión de edición y los endpoints existentes para buscar, autocompletar y mostrar el mapa. El vendedor revisa y confirma los valores. Si Google no devuelve municipio o colonia, los campos se completan manualmente; no se sustituye municipio por localidad.

El mapa es opcional para confirmar. Los resultados crudos, referencias temporales y coordenadas Google no se copian a las revisiones duraderas. La dirección y zona históricas no cambian por refrescar el mapa. Se aplican las reglas del [ADR Google](../adr/0001-google-ubicacion-beta-rc.md), manteniendo explícita la procedencia de lo temporal y de los datos comerciales. La confirmación humana por sí sola no cambia la retención de datos del proveedor.

Reutilizar el componente exige adaptar su contexto al usuario del CRM y permitir una ubicación sin captación previa; no crear una cuenta ficticia de propietario. El diseño detallado debe comprobar que ningún requisito exclusivo de captación, como teléfono confirmado o mapa obligatorio rural, se aplique accidentalmente al cierre histórico.

## Flujo del CRM

Corrección de Guillermo del 22 de noviembre, que sustituye la navegación anterior de Q29:

1. Desde Propiedades o la captación vinculada, elegir Marcar vendida o Marcar rentada cuando la operación realmente ocurrió. No hay pestaña independiente de cierres.
2. Reutilizar los datos de origen. `Property.private_data` conserva la dirección exacta privada del alta interna; las captaciones conservan su información validada. Terreno, construcción y superficie privativa son campos separados en ambas vías. Si faltan datos, editar la ficha de origen.
3. Añadir precio final, moneda y fecha real. El precio solicitado permanece separado y no se infiere un cierre por despublicar.
4. Revisar el resumen y confirmar con permiso explícito. La preparación obtiene los datos del servidor y comprueba la revisión de la fuente; confirmar revalida el resumen.
5. Consultar estado e historial desde la propiedad. Las correcciones conservan sus versiones.
6. Si no se concretó la operación, usar Retirar con motivo. Se conservan ficha, captación, acuerdos aceptados y eventos; no se crea `Closing`. Volver a comercializar exige acción expresa y deja la oferta despublicada para revisión, sin revivir contratos.

`PropertyEvent` y las nuevas copias de `CaptureEvent` conservan hechos comerciales privados aun sin venta/renta; excluyen referencias y coordenadas temporales Google. La migración `0016` incorpora datos privados existentes desde captación y un evento de línea base sin inventar eventos pasados. La carga excepcional de operaciones anteriores queda accesible desde inventario y permite históricos sin oferta; no integra el recorrido de un cierre actual.

La lista permite filtrar por estado, venta/renta, fecha, zona, tipo y marca de prueba. Es administración de cierres, no una herramienta de comparación. El detalle muestra por separado precio final, cargos, superficies, datos faltantes e historial. Los registros de prueba quedan visibles como tales para el equipo.

El autor o administrador puede editar o eliminar borradores nunca confirmados. Una persona con permiso de cierres puede confirmar un borrador preparado por otra persona sin sobrescribir silenciosamente su trabajo. Se revalida permiso al ejecutar la acción, no solo al mostrar el botón.

## Confirmación consistente y reintentos

La confirmación se realiza en una transacción corta, sin llamadas a Google o a servicios de mensajería dentro de ella:

1. Comprobar usuario, autorización vigente, revisión esperada y clave única de solicitud.
2. Bloquear en el orden autorización vigente, identidades físicas ordenadas por UUID, captaciones por clave, ofertas por clave y cierres por UUID. Se omiten los grupos que no intervienen. Las rutas anteriores conservan `Capture → Property` y no adquieren después bloqueos de grupos anteriores; consultan la guarda de cierre bajo el bloqueo de la oferta. La revisión se vuelve a validar después de adquirir todos los bloqueos pertinentes.
3. Revalidar identidad, fuente, mínimos, oferta y posibles cierres duplicados. Una aceptación previa de advertencias queda obsoleta si surgió otro cierre concurrente.
4. Conservar revisión confirmada y quién la confirmó.
5. Solo para el cierre de oferta actual: despublicar esa oferta, registrar fin de comercialización por cierre y terminar acuerdos abiertos sin alterar copias aceptadas. Hacerlo todo o revertir toda la transacción.
6. Registrar avisos internos al asesor si existen visitas futuras; mantener las citas. Persistir los avisos con una clave única para no duplicarlos en reintentos.

Una respuesta HTTP perdida o doble clic no crea otro cierre ni otro aviso. La misma clave con datos distintos se rechaza. Guardar borrador, cargar un histórico, corregir, anular o revertir no ejecuta de nuevo los efectos comerciales de la primera confirmación.

No se impone unicidad por inmueble/tipo/fecha: la advertencia de Q36 admite decisión humana. Sí debe impedirse cerrar simultáneamente dos veces la misma oferta en el mismo periodo de comercialización. Q39 admite un periodo nuevo solo tras anulación y reapertura expresa, conservando el cierre anulado.

Edición de inventario, publicación, revisión/renovación/aceptación de captación y mantenimiento deben respetar el fin por cierre. Una ruta anterior no puede publicar una oferta cerrada saltándose la nueva regla. Anulación y reversión no reabren comercialización por sí solas.

### Reapertura tras un cierre erróneo

Se incorpora Q39 con una acción privada propia, no mediante editar el estado o publicar directamente:

1. Comprobar permiso explícito, motivo y revisión esperada. Exigir que el cierre causante del fin de esa oferta esté anulado porque la operación nunca ocurrió.
2. Conservar el cierre anulado y sus revisiones. Abrir un nuevo periodo de comercialización de esa misma oferta mediante evento con autor, fecha y motivo.
3. Mantener la oferta despublicada hasta cumplir las condiciones de publicación que le correspondan. Si existe captación, requiere revisión y exclusividad vigente aceptada; los acuerdos terminados no se reactivan cambiando su fecha de fin. No se impone una nueva cuenta/contrato a ofertas anteriores que no lo requerían.
4. Un cierre posterior crea otro registro y conserva el vínculo con el mismo inmueble. Una operación nueva posterior a un cierre real, incluido uno revertido después, utiliza otra oferta, conforme a Q39.

Para hacer comprobable la excepción sin debilitar Q36, la oferta lleva un número de periodo comercial. Al confirmar se crea un vínculo persistente oferta/periodo/cierre, único por oferta y periodo, dentro de la misma transacción. Ese vínculo no se elimina al anular ni revertir. Reabrir por error incrementa el periodo una sola vez y deja el vínculo anterior intacto. Doble clic o reintento de reapertura devuelve el mismo resultado por clave de solicitud, sin incrementar otra vez el periodo.

Las correcciones de importe o características no modifican estos vínculos ni el periodo. El histórico puede referenciar una oferta, pero no crea un fin comercial ni altera su periodo actual. Reabrir no vuelve a abrir búsquedas ni envía mensajes.

## Efectos sobre prospectos y citas

El comprador se selecciona explícitamente. Vincularlo no modifica su estado general, consentimiento de contacto ni otras búsquedas. Un histórico no cambia seguimientos vigentes.

La acción opcional «Dar por atendida esta búsqueda» recibe una identidad de intención explícita, comprueba que pertenece al comprador seleccionado y guarda el vínculo con el cierre. La confirmación del cierre y esta acción se presentan separadas para que resolver una búsqueda nunca sea un efecto implícito.

Una conversación, en especial WhatsApp, puede contener varias intenciones sucesivas y `FollowupCycle` solo admite un ciclo abierto por prospecto. `SearchIntent` identifica cada búsqueda y el ciclo se relaciona con esa identidad, conservando la restricción actual. Cambiar criterios o consultar otra propiedad dentro de una búsqueda no crea por sí solo otra intención. No basta un indicador de «resuelta» sobre toda la conversación.

Resolver la intención seleccionada cierra exclusivamente su ciclo pendiente con motivo propio y conserva sus requisitos e historial. No llama a `set_permission(False)`, no cambia el prospecto a «Sin interés» ni reutiliza el cierre especial de un piloto que restaura una baja global. Una intención ya resuelta no se reactiva con Reanudar; una intención posterior sigue el recorrido explícito existente de Nueva intención y requiere interacción posterior. Corregir, anular o revertir el cierre no resucita búsquedas automáticamente.

Programación, selección de plantilla y transporte final deben comprobar la resolución y los requisitos de esa intención. Los trabajos pendientes se invalidan de forma acotada; memoria y CRM muestran que la búsqueda fue atendida sin incorporar precio final ni dirección privada al contexto público del agente. Una entrega ya aceptada por el proveedor no puede retirarse; la comprobación previa al envío impide iniciar nuevos envíos de la búsqueda resuelta, pero no promete recuperar un mensaje en tránsito.

La incorporación de datos existentes vincula un ciclo a una intención identificada por él, sin fusionar ciclos históricos solo por compartir conversación. Si falta evidencia para adjudicar una búsqueda a una operación antigua, no se infiere resolución; el vínculo debe elegirlo el equipo. La acción no crea mensajes de prueba ni reabre seguimientos para validar el diseño.

Las citas existentes se conservan, incluidas las de otros interesados. Se avisa al asesor, que decide cómo proceder. `inventory.notify_unpublished` llama actualmente a un helper que también puede responder por WhatsApp sobre una cita. No debe reutilizarse sin separar el aviso interno de esa respuesta; cerrar una oferta no autoriza mensajes adicionales a prospectos.

## Contrato privado

Rutas privadas implementadas:

| Ruta | Métodos y uso |
| --- | --- |
| `/api/crm/closings` | GET lista filtrada y paginada; POST crea borrador. |
| `/api/crm/closings/<id>` | GET ficha e historial; PUT edita borrador; DELETE elimina borrador nunca confirmado. |
| `/api/crm/closings/<id>/preview` | GET resumen y prueba de vigencia. |
| `/api/crm/closings/<id>/actions` | POST confirma, corrige, anula, revierte, reabre o resuelve la búsqueda seleccionada. |
| `/api/crm/closings/permissions` | GET/POST administra permiso explícito y muestra historial. |
| `/api/crm/closings/identities` | GET busca identidades; POST vincula dos identidades mediante decisión humana auditada. |
| `/api/crm/closings/searches` | GET lista las búsquedas del comprador seleccionado. |
| `/api/crm/closings/offers/<id>/proposal` | GET propone características de una oferta actual para revisión, sin convertir precio solicitado en precio final. |

Responsabilidades:

- Listar y consultar cierres e historial; buscar/seleccionar identidad física sin exponer datos privados al público.
- Crear y actualizar borrador con revisión esperada; eliminar solo borrador nunca confirmado.
- Preparar resumen y confirmar con revisión esperada, clave de solicitud y revisión de posibles duplicados.
- Corregir, anular o revertir con motivo, revisión esperada y clave de solicitud.
- Reabrir oferta tras anulación por error, con permiso, motivo, revisión esperada y clave de solicitud; conservarla despublicada hasta reunir las condiciones pertinentes.
- Administrar permiso explícito con auditoría. El usuario ve las acciones permitidas; el backend siempre vuelve a comprobarlas.

Fechas ISO cuando sean completas; fechas parciales como componentes explícitos; importes/superficies decimales serializados como texto. Errores de campos usan el contrato compartido existente. Conflictos de revisión exigen recargar/revisar, sin reintento automático de escrituras. Un registro confirmado no admite un PATCH genérico que eluda su historial.

Las proyecciones públicas, cuenta del propietario y herramientas públicas no incorporan datos de cierres. `public_property` expone `Property.details`; por eso no se guardan allí dirección privada ni precios finales. El dueño podrá ver el estado comercial que corresponda, sin exponer el registro privado del cierre.

## Ubicación del código y migración

- Modelos y migraciones aditivas en `backend/datalayer`; contratos de entrada en `closing_schemas.py`; consultas y transacciones en `closings.py`. Imports desde `datalayer.models`.
- Transporte privado en `backend/api`; pantalla y coordinación de formulario en `frontend/src/crm`; entrada mínima en `frontend/src/app`. Reutilizar controles monetarios, ubicación y errores compartidos.
- La cola existente entrega avisos; no se añaden servicios, bases de datos ni herramientas del agente para registrar cierres.
- Conservar etiqueta Django `core`, tablas anteriores, referencias y claves públicas. Crear identidades separadas provisionales para las ofertas existentes sin afirmar equivalencia o diferencia física; vincular coincidencias solo con decisión humana. La vinculación posterior debe preservar revisiones y referencias originales, sin borrar identidades utilizadas por el historial.
- No inferir cierres, fechas o precios finales desde publicaciones, exclusividades, citas, opiniones de valor ni precios solicitados. No migrar características actuales como hechos históricos.
- `Property.area_m2` se presenta hoy como construcción; terreno está en datos adicionales de captación. Mapearlos explícitamente al proponer una ficha para un cierre actual. No hay campo privativo existente: queda desconocido hasta captura humana.

Puntos existentes que deben aplicar la guarda duradera de fin de oferta: `save_property`, `set_publication`, revisión de captación (`update`, `approve`, `renew`, `withdraw`, `reject`, `publish`), aceptación de acuerdo, solicitud de renovación del propietario y administrador Django. El marcador no depende únicamente de `Capture.status` ni desaparece al anular/revertir el cierre. La reapertura excepcional de Q39 debe pasar por una acción propia y dejar evento.

## Plan de implementación y aceptación

Las etapas son de construcción, no entregas funcionales que omitan acuerdos:

1. Añadir modelo, migración, permisos, historial y pruebas de integridad. Validar migración con copia de datos, manteniendo conteos, referencias, citas y publicaciones.
2. Implementar transacciones y API privada. Probar permisos revocados, concurrencia, doble clic, respuesta perdida, revisión obsoleta, anulación/reversión, reapertura explícita y protección de publicaciones.
3. Implementar CRM y reutilización de Google. Probar captura desde oferta e histórico, fechas parciales, superficies desconocidas, monedas/cargos, dirección rural y correcciones con historial.
4. Integrar avisos y resolución explícita de intención según contrato cerrado. Probar que citas y otras búsquedas se conservan y que no se crean envíos de WhatsApp por confirmar un cierre.
5. Ejecutar suite existente, controles del frontend y comprobación de rutas. Realizar aceptación de extremo a extremo con registros marcados de prueba; la marca no simula efectos ni autoriza envíos.

Casos de aceptación que deben quedar demostrados:

- Un mismo inmueble conserva una renta y una venta, con fechas, precios y características independientes.
- Una remodelación o cambio de ficha actual no modifica una operación pasada.
- Un histórico incompleto se conserva sin inventar fecha o superficie; faltantes obligatorios impiden confirmar y características opcionales no.
- Consultas internas recuperan zona, tipo, moneda, precio final y las distintas superficies sin interpretar notas. Se pueden verificar matemáticamente cocientes por m² sin añadir una interfaz de comparación.
- Confirmar la oferta A no altera otra oferta B del mismo inmueble, ni publica información privada, ni cambia búsquedas de otros prospectos.
- Corrección, anulación y reversión conservan versiones anteriores; prueba/anulado/revertido no se presentan como operaciones válidas para futuros comparables.
- Anular no republica ni libera por sí solo una oferta para otro cierre. Reabrir exige motivo y autorización, conserva el cierre anulado y no revive exclusividad; un cierre posterior queda en otro periodo. Dos solicitudes concurrentes no crean dos periodos ni dos cierres del mismo periodo.

## Revisión final y comprobaciones de implementación

Las preguntas de negocio Q1–Q39 están resueltas. Guillermo aprobó el conjunto y autorizó la implementación en el orden propuesto. La evidencia de pruebas y migración está en el informe de validación; la aceptación funcional del producto sigue siendo distinta de la aprobación del diseño.

Al implementar se comprobarán expresamente dos contratos transversales: la identidad de búsqueda en todos los puntos de creación/reanudación/envío, y la separación de datos comerciales duraderos y resultados Google temporales. Estas comprobaciones forman parte del trabajo, no se trasladan al vendedor ni se sustituyen por un estado global de prospecto o por su confirmación de dirección.

La primera entrega verificable incluirá identidad física, registro de cierres, revisiones, permisos y migración compatible. Los siguientes bloques añaden confirmación/reapertura y guardas de publicación, CRM, resolución explícita de búsqueda y aceptación integral. El alcance completo sigue siendo Q1–Q39; ningún bloque intermedio se presentará como terminado si faltan acuerdos del conjunto.

## Evidencia de integración consultada

`backend/datalayer/models.py`, `closing_schemas.py`, `closings.py`, `capture_schemas.py`, `captures.py`, `capture_approval.py`, `inventory.py`, `appointments.py`, `google_locations.py`; `backend/api/closings.py`, `location.py`; `frontend/src/crm/components/Closings.tsx`, `frontend/src/shared/lib/location-editing.ts`; [organización del código](../architecture/code-structure.md) y los ADR de ubicación e identidad.
