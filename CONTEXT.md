# Plataforma para inmobiliarias

## Language

**Inmobiliaria**:
Organización que utiliza la plataforma para gestionar su inventario de propiedades, equipo y atención comercial.
_Avoid_: Brokerage

**Asesor inmobiliario**:
Persona del equipo de una inmobiliaria que atiende operaciones y realiza el trabajo comercial que requiere intervención humana.
_Avoid_: Broker, agente humano

**Inventario de propiedades**:
Conjunto de propiedades que una inmobiliaria ofrece en venta o renta. Pertenecer al inventario no implica que la inmobiliaria sea propietaria del inmueble.
_Avoid_: Stock

**Propiedad importada de EasyBroker**:
Oferta incorporada al inventario de Maia desde EasyBroker, conservando su procedencia. Importarla no acredita una operación realizada ni cambia por sí misma la titularidad del inmueble.
_Avoid_: Cierre confirmado, propiedad de la inmobiliaria

**Importación automática de inventario**:
Incorporación y actualización de ofertas desde una fuente autorizada sin capturar cada propiedad a mano. Importar una oferta no equivale a aprobar su publicación en Maia.
_Avoid_: Publicación automática, acceso a todo el inventario del proveedor

**Cuenta de origen EasyBroker**:
Cuenta autorizada de la que procede una oferta importada. Una misma operación de Maia puede reunir inventario de las cuentas de Guillermo, Santiago y otros socios, conservando la procedencia de cada oferta.
_Avoid_: Cuenta del propietario del inmueble, usuario del CRM

**Fuente principal de una oferta importada**:
Anuncio de origen elegido por el equipo para determinar los datos de una oferta que está relacionada con varias fuentes. Las otras vinculaciones se conservan y no sustituyen a la principal automáticamente.
_Avoid_: Fuente más reciente, mezcla de precios de varias cuentas

**Texto público aprobado**:
Título y descripción revisados por el equipo para presentarse al público y en las respuestas de Maia. Son distintos del texto recibido del origen, que puede contener información privada o cambios todavía sin aprobar.
_Avoid_: Descripción importada como autorización de publicación

**Ocultación por información caducada**:
Suspensión de una oferta porque transcurrieron 24 horas sin una comprobación válida de su disponibilidad. Puede levantarse al recuperar una comprobación válida solo si era el único impedimento y se conserva la aprobación necesaria.
_Avoid_: Baja confirmada en origen, retirada manual, eliminación de la ficha

**Precio por consultar**:
Presentación de una oferta cuyo importe no está autorizado para mostrarse al público. Permite solicitar información al asesor sin publicar el precio ni tratarlo como cero.
_Avoid_: Gratis, sin precio conocido por el equipo, precio público pendiente de copiar

**Despublicación local de una oferta importada**:
Decisión del equipo de ocultar una oferta del sitio y las recomendaciones de Maia, conservando su ficha e historial. No modifica EasyBroker y permanece vigente durante las importaciones posteriores hasta que el equipo la cambie expresamente.
_Avoid_: Borrado del inmueble, baja en EasyBroker, cierre de venta o renta

**Baja de una oferta en origen**:
Retirada o indisponibilidad confirmada de una oferta en la cuenta EasyBroker de la que procede. Impide seguir ofreciéndola en Maia, pero conserva sus datos e historial sin exigir conservar fotografías y no acredita una venta o renta realizada.
_Avoid_: Fallo de conexión, eliminación de la ficha, cierre confirmado

**Inmueble**:
Bien inmueble físico cuya identidad se conserva a través de sus distintas ventas o rentas.
_Avoid_: Publicación, operación realizada

**Operación realizada**:
Venta o renta concretada de un inmueble. Un mismo inmueble puede acumular operaciones realizadas independientes en distintos momentos.
_Avoid_: Tipo de operación, solicitud de captación, anuncio

**Historial de operaciones**:
Registro de ventas y rentas de un inmueble, con sus precios finales, características al cierre y posteriores correcciones, anulaciones o reversiones.
_Avoid_: Historial de precios anunciados, seguimiento de rebajas de la oferta

**Oferta de comercialización**:
Oferta de un inmueble en venta o renta que puede publicarse o retirarse del inventario. Es distinta del inmueble físico y de la operación que finalmente se concrete.
_Avoid_: Oferta de compra del prospecto, cierre de operación

**Prospecto**:
Persona interesada en comprar o rentar una propiedad.
_Avoid_: Lead, cliente cuando todavía solo existe interés comercial

**Propietario**:
Persona dueña de un inmueble que desea ofrecerlo en venta o renta mediante la inmobiliaria. Enviar sus datos no acredita por sí solo la titularidad.
_Avoid_: Prospecto, cuando se refiere a quien ofrece el inmueble

**Solicitud de captación**:
Información que una persona envía para que la inmobiliaria evalúe incorporar un inmueble a su inventario. No equivale a una propiedad publicada.
_Avoid_: Anuncio publicado, publicación automática

**Precio solicitado**:
Importe que el propietario propone para vender o rentar el inmueble. No equivale a una opinión de valor de la inmobiliaria.
_Avoid_: Valor de mercado, avalúo

**Opinión de valor**:
Estimación comercial que Santiago o el asesor designado revisa y comunica al propietario para orientar el precio del inmueble.
_Avoid_: Avalúo certificado, valoración automática

**Cierre de operación**:
Confirmación explícita de un asesor autorizado de que una venta o renta se concretó, con fecha e importe finales. Una oferta aceptada o un apartado no constituyen un cierre.
_Avoid_: Cita, despublicación, aceptación de exclusividad

**Precio de cierre**:
Precio base final confirmado del inmueble en una venta, o mensualidad base final en una renta, expresado en la moneda de la operación. Los cargos adicionales se registran por separado.
_Avoid_: Precio solicitado, opinión de valor, avalúo

**Fecha de cierre**:
Fecha de firma de la escritura en una venta o de firma del contrato en una renta. Es distinta de las fechas de captura y confirmación del registro.
_Avoid_: Fecha de publicación, fecha de registro como sustituto de la fecha real

**Referencia o notas del cierre**:
Anotación opcional sobre el origen del dato de una operación, como la confirmación de un asesor o la referencia a un contrato. No exige adjuntar documentos.
_Avoid_: Comprobante obligatorio, validación documental del cierre

**Dirección exacta del cierre**:
Domicilio privado compuesto por estado, municipio, colonia, calle, número exterior e interior cuando corresponda. Identifica la ubicación declarada para la operación y no exige por sí mismo un punto en el mapa.
_Avoid_: Zona aproximada, coordenadas Google temporales como sustituto del domicilio

**Identificación rural del cierre**:
Identificación de un predio sin domicilio postal convencional mediante estado, municipio, localidad y datos de predio, lote o parcela respaldados por una referencia documental que lo individualice. La descripción de acceso la complementa.
_Avoid_: Referencia vaga de acceso, dirección postal inventada

**Cargos adicionales**:
Importes de mantenimiento, impuestos, comisiones, depósitos u otros conceptos relacionados con una operación, separados de su precio base. Un desglose desconocido no equivale a un cargo de cero.
_Avoid_: Precio de cierre con todos los gastos incluidos

**Resultado de comercialización**:
Desenlace de la comercialización de una propiedad. Una venta o renta realizada añade precio final y fecha reales a los datos ya conocidos del inmueble. Retirar la propiedad o cancelar el contrato sin concretar la operación conserva sus datos e historial, pero no constituye una venta ni una renta.
_Avoid_: Despublicación como prueba de venta, cancelación como cierre realizado

**Borrador histórico**:
Registro pendiente de completar de una operación propia pasada que todavía carece de datos necesarios para confirmar el cierre, como precio final, fecha o dirección exacta.
_Avoid_: Cierre confirmado completo, importe o fecha estimados presentados como hechos

**Características del inmueble al cierre**:
Datos del inmueble tal como era cuando se concretó una operación. Se conservan para esa operación aunque después el inmueble cambie; lo desconocido permanece sin completar.
_Avoid_: Ficha actual aplicada automáticamente a una venta o renta pasada

**Zona del cierre**:
Colonia, barrio o localidad del inmueble registrada de forma estructurada junto con su estado y municipio para futuras comparaciones. Complementa la dirección exacta, sin sustituirla.
_Avoid_: Dirección completa como único texto, zona deducida solo del nombre de la colonia

**Precio de cierre por m²**:
Cociente entre el precio final de una operación y una superficie conocida del inmueble, identificada expresamente como terreno, construcción o superficie privativa. Conserva la moneda y, en renta, expresa una mensualidad por m². No representa por sí solo una valuación ni separa el valor del suelo y la edificación.
_Avoid_: Precio por metro sin superficie de referencia, costo de construcción

**Ficha incompleta del inmueble**:
Ficha que identifica el inmueble, su tipo, zona y dirección exacta, pero conserva características desconocidas. Puede acompañar un cierre confirmado si están completos los datos de la operación.
_Avoid_: Cierre no realizado, valores faltantes interpretados como cero o ausencia

**Comprador o arrendatario vinculado**:
Persona que el equipo identifica expresamente como comprador o arrendatario de una operación concreta. El vínculo es opcional; un interés o una cita no lo acreditan por sí solos.
_Avoid_: Cualquier interesado en el inmueble, participante deducido automáticamente

**Registro de prueba**:
Registro que el equipo marca manualmente como prueba y que se excluye de futuros comparables. La marca clasifica la información; no simula las acciones de la plataforma.
_Avoid_: Otra base de datos, modo de simulación, operación real inferida del nombre

**Corrección de cierre**:
Rectificación de los datos de un cierre confirmado que conserva el dato original, la modificación, su autor, fecha y motivo.
_Avoid_: Sobrescritura sin historial, nueva operación

**Anulación de cierre**:
Invalidación de un registro de cierre creado por error cuando la operación no se concretó. Conserva el registro, motivo, autor y fecha; no vuelve a publicar el inmueble por sí sola.
_Avoid_: Borrado del cierre, corrección de importe, cancelación jurídica de una operación realizada

**Reversión de operación**:
Registro de que una operación que sí se concretó posteriormente se revirtió, con fecha, motivo y responsable. Conserva el cierre original y no reactiva publicaciones ni seguimientos por sí sola.
_Avoid_: Anulación de un cierre que nunca ocurrió, borrado de la operación

**Reapertura de oferta por cierre erróneo**:
Acción expresa de una persona autorizada para volver a comercializar una oferta cuyo cierre fue anulado porque la operación nunca ocurrió. Conserva el cierre anulado, registra motivo y responsable y exige revisar las condiciones de publicación y exclusividad. Una venta o renta posterior se registra como un cierre nuevo.
_Avoid_: Republicación automática al anular, restauración del cierre erróneo o de acuerdos terminados

**Persona autorizada para registrar cierres**:
Integrante activo del equipo con acceso al CRM, sin habilitación adicional para registrar operaciones. Puede ser diferente del asesor responsable; cada cambio conserva quién lo realizó y su correo en ese momento.
_Avoid_: Permiso adicional de cierres, cuenta externa de propietario

**Intención atendida por cierre**:
Búsqueda vinculada a un comprador o arrendatario que el asesor marca expresamente como resuelta al registrar su operación. No constituye una baja general de contacto ni resuelve otras búsquedas.
_Avoid_: No desea mensajes, cierre automático de todas las conversaciones

**Exclusividad de comercialización**:
Acuerdo por el que el propietario concede a la inmobiliaria la comercialización exclusiva de su inmueble en la operación pactada. Se exige tanto para venta como para renta y no transfiere la propiedad del inmueble.
_Avoid_: Exclusividad de venta, cuando también comprende renta; plan de publicación; propiedad de la inmobiliaria

**Representante autorizado**:
Persona facultada por el propietario para gestionar la captación del inmueble. La inmobiliaria verifica esa representación antes de publicar.
_Avoid_: Propietario, cuando actúa en nombre de otra persona

**Cuenta del propietario**:
Cuenta con email, teléfono y contraseña que permite al propietario o representante autorizado gestionar sus solicitudes de captación. Tener una cuenta no acredita titularidad ni concede permiso para publicar sin revisión.
_Avoid_: Prospecto, cuenta del asesor


**Preventa**:
Comercialización anticipada de un inmueble en venta. Es una condición comercial independiente del tipo de inmueble, la conservación y la antigüedad.
_Avoid_: Temporada, tipo de inmueble

**Ubicación exacta del inmueble**:
Dirección y punto geográfico privados de la captación, disponibles al propietario y al equipo autorizado. Su publicación requiere autorización expresa del equipo.
_Avoid_: Ubicación pública, ubicación verificada, cuando solo se recibió una dirección o un punto

**Ubicación pública aproximada**:
Referencia geográfica que permite explorar la zona del inmueble sin publicar su dirección ni punto exactos. No sustituye la ubicación privada de la captación.
_Avoid_: Dirección del inmueble, ubicación exacta

**Referencia de ubicación del inmueble**:
Descripción aportada por el propietario para localizar un terreno o rancho sin dirección convencional. Junto con estado, municipio y punto en el mapa permite presentar la captación a revisión, sin inventar calle, número o colonia.
_Avoid_: Dirección verificada, colonia, cuando solo se describe cómo llegar al inmueble


**Aprobación de captación**:
Resultado de la revisión del equipo que permite solicitar al propietario la aceptación de la exclusividad. No equivale a aceptación ni a publicación. Una corrección comercial exige una nueva revisión.
_Avoid_: Propiedad publicada, contrato aceptado

**Copia de contrato de exclusividad**:
Documento con el contenido comercial y las condiciones que se presentan al propietario para aceptar la exclusividad. La copia enviada conserva el contenido de su aprobación, aunque después cambie la solicitud.
_Avoid_: Formulario actual, cuando se habla de una copia ya emitida
