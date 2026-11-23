# Cierres de operaciones y preparación de comparables

## Corrección vigente: sesión y autoría · 22 de noviembre de 2026

Guillermo elimina el permiso adicional de cierres, también para administradores. Una cuenta activa del equipo con sesión CRM puede registrar y actualizar operaciones. Se retiran los controles de permisos y su endpoint; las antiguas tablas de autorización se conservan únicamente como datos históricos, sin condicionar acciones. Se mantiene la autenticación del equipo, CSRF, revisión del resumen y control de concurrencia.

Cada nueva revisión de operación y evento de propiedad/captación, además de las vinculaciones de inmuebles, conserva el identificador y una copia del correo del autor obtenidos de la sesión en el servidor. Un correo enviado por el cliente no decide la autoría. Cambiar después el correo de la cuenta no reescribe el historial. Los eventos previos conservan su identificador; no se inventa el correo que tenían entonces. La migración 0017 añade esos campos sin cambiar los datos anteriores. Esta decisión sustituye los requisitos anteriores de habilitación adicional.

Iniciado el 20 de noviembre de 2026; actualizado el 22. Estado: Q1–Q39 resueltas y diseño aprobado por Guillermo. Implementación local con [validación documentada](../testing/cierres-y-comparables.md). Q37 reutiliza Google como ayuda de captura y Q38 establece confirmación humana de los datos, sin algoritmo de verificación.

El [diseño técnico](cierres-modelo-tecnico.md) desarrolla modelo, flujo del CRM, migración, contratos y aceptación. Guillermo autorizó su implementación en el orden acordado después de resolver Q39.

## Corrección de flujo de Guillermo · 22 de noviembre de 2026

Esta decisión sustituye Q29 en cuanto a navegación y recaptura: no habrá pestaña independiente de cierres. El cierre ocurre cuando el asesor concreta la venta o renta y lo registra desde la propiedad. Dirección, zona, superficies y características se capturan desde el propietario externo o desde el alta interna del CRM. El resultado reutiliza esa ficha y añade precio final y fecha reales, sin tomar el precio anunciado como precio de cierre. Si faltan datos de origen, se corrigen en la ficha.

Retirar la propiedad, cancelar el contrato o no concretar la operación conserva los datos, acuerdos aceptados e historial; no crea una venta o renta. Las operaciones anteriores se conservan como herramienta excepcional de carga histórica, fuera del recorrido habitual. Se mantienen identidad física, permisos y revisiones auditadas. Los acuerdos anteriores que describen la pestaña quedan como antecedente, sustituidos por esta corrección.

## Objetivo acordado

Conservar datos fiables de inmuebles y operaciones realizadas para poder comparar, a mediano plazo, ventas de propiedades con características similares. Este trabajo prepara información histórica; la opinión de valor manual existente y el cálculo automático de una valoración son alcances distintos.

## Hechos de partida

- La ficha y la captación guardan características estructuradas y validadas; varias son opcionales. Fuentes: `backend/datalayer/models.py`, `capture_schemas.py` y `captures.py`.
- El precio actual corresponde a la oferta. No existe un registro específico de precio final y fecha de una venta realizada.
- Publicación, aprobación, exclusividad, retirada y vencimiento describen comercialización. Ninguno acredita por sí solo una venta.
- Los acuerdos de exclusividad conservan copias históricas de sus datos comerciales. No son copias del inmueble al cerrar una operación. Los eventos actuales no constituyen un historial estructurado de todos los cambios de precio.
- El modelo actual vincula una captación con una propiedad. Se acordó conservar un mismo inmueble con operaciones independientes; la propuesta técnica conserva las referencias existentes y añade una identidad física común sin inferir fusiones.
- La ubicación obtenida de Google es temporal según el [ADR vigente](../adr/0001-google-ubicacion-beta-rc.md). El histórico no puede asumir que ese punto es permanente ni copiarlo sin respetar su fuente y retención.
- El [glosario](../../CONTEXT.md) distingue precio solicitado, opinión de valor, cierre de operación y precio de cierre. La admisión de un registro como comparable sigue por definir.

## Necesidades que debe resolver el diseño

Registrar el resultado real de una operación, su precio final base/moneda y fecha; conservar las características relevantes del inmueble en ese momento y el historial de las operaciones, correcciones, anulaciones y reversiones. **No se incluye registrar la evolución de precios solicitados o anunciados.** Se acordaron mínimos de confirmación y una referencia opcional al origen del dato; el detalle de los campos y la admisión futura como comparable siguen abiertos.

Guillermo requiere que los datos permitan comparar por zona (colonia, barrio u otra referencia local) y precio por m². La dirección exacta se conserva; la zona debe poder consultarse como dato estructurado, no quedar únicamente en notas. Se conservarán superficies de terreno y construcción separadas y superficie privativa identificada para departamentos, con precio final, moneda y fecha. Todo cociente futuro identificará la superficie utilizada; dividir el precio total entre una superficie no aísla el valor del suelo ni de la construcción. Esta necesidad no adelanta el comparador ni la valoración automática a esta entrega.

## Árbol de decisiones

Primera ronda, resuelta:

- Q1. Registro de cierres e historial primero; consulta de comparables fuera de esta entrega.
- Q2. Ventas y rentas, diferenciadas.
- Q3. Operaciones propias nuevas e históricas aportadas por el equipo; fuentes externas fuera de esta entrega.
- Q4. Cierre confirmado explícitamente por un asesor autorizado, con fecha y precio finales. Ofertas aceptadas y apartados no cuentan como operaciones realizadas.

Segunda ronda, resuelta:

- Q5. Todos los tipos del catálogo actual, sin ampliarlo.
- Q6. Un mismo inmueble con operaciones independientes. Cada operación conserva las características del inmueble en su cierre.
- Q7. Permiso explícito para registrar cierres; no se limita al asesor asignado. Registrar por separado al responsable de la operación y a quien confirma.
- Q8. Correcciones con historial: conservar original, modificación, autor, fecha y motivo.

Tercera ronda, resuelta:

- Q9. Precio del inmueble en venta y mensualidad base en renta. Cargos adicionales separados; no inventar desgloses desconocidos.
- Q10. Venta: firma de escritura. Renta: firma de contrato. Captura y confirmación conservan fechas propias, distintas de la fecha real de cierre.
- Q11. Históricos sin precio final o fecha se guardan como borradores pendientes de completar; no se presentan como cierres confirmados completos.
- Q12. Para confirmar: inmueble identificado, tipo, zona, operación, precio, moneda y fecha. Superficie, antigüedad y amenidades desconocidas no impiden confirmar: permanecen vacías y la ficha se señala como incompleta. No se da por aprobada su calidad como comparable.

Cuarta ronda, resuelta:

- Q13. Confirmar el cierre despublica únicamente la oferta vinculada que se está cerrando. La carga histórica no modifica ofertas actuales.
- Q14. Registrar el fin de la comercialización por cierre, preservando el acuerdo aceptado y su historial. Distinguirlo de retirada y vencimiento.
- Q15. Un cierre registrado por error cuando la operación no se concretó se anula con motivo, autor y fecha, conservando el registro y excluyéndolo de futuros comparables. No se republica automáticamente.
- Q16. Sugerir coincidencias y exigir confirmación humana para vincular registros. Dirección, interior/unidad y otras referencias ayudan, pero compartir dirección no prueba identidad ni autoriza fusión automática.

Quinta ronda, resuelta:

- Q17. Guillermo exige **dirección exacta** para confirmar el cierre; estado y municipio por sí solos no bastan. Este requisito se añade a los mínimos de Q12. Los registros históricos que carezcan de ella no cumplen todavía los requisitos de confirmación. La composición de la dirección y el tratamiento rural se precisarán en la siguiente ronda.
- Q18. Vínculo opcional con un prospecto existente como comprador/arrendatario. Se admiten históricos sin recopilar nuevos datos personales. No inferir el vínculo de intereses o citas.
- Q19. Lectura de cierres y precios finales para el equipo del CRM; permiso explícito para confirmar, corregir y anular. No se muestran al público ni en la cuenta del propietario en esta entrega.
- Q20. Marca manual de registro de prueba, en la misma base, excluido de futuros comparables. No cambia las acciones reales en simulaciones.

Sexta ronda, resuelta:

- Q21. Domicilio con estado, municipio, colonia, calle, número exterior e interior cuando corresponda. Punto de mapa opcional, que no sustituye la dirección. Los datos temporales Google siguen sujetos al ADR vigente.
- Q22. Alternativa rural: estado, municipio, localidad e identificación del predio/lote/parcela con referencia documental que lo individualice. Descripción de acceso complementaria. Sin identificación suficiente permanece como borrador.
- Q23. Ofrecer al asesor una acción explícita para dar por atendida únicamente la intención vinculada al comprador/arrendatario. No dar de baja general de contacto ni modificar búsquedas vigentes al cargar históricos.
- Q24. Solo administradores conceden o revocan el permiso de cierres, con registro de autor y fecha. Una ficha de asesor no concede acceso por sí sola.

Séptima ronda, resuelta:

- Q25. Campo «Referencia o notas» opcional para indicar de dónde salió el dato, por ejemplo «Santiago confirmó el importe» o «Contrato de 2022». Sin exigir documentos ni validaciones adicionales.
- Q26. Solo precios finales a los que se vendió o rentó. Se descarta el historial propuesto de precios solicitados y publicación. Se conserva el historial de operaciones y de correcciones de datos confirmado en Q8.
- Q27. Reversión separada de una operación que sí ocurrió: fecha, motivo y responsable; conservar el cierre original, excluirlo de futuros comparables y no republicar ni reabrir seguimientos automáticamente.
- Q28. Borrado ordinario solo de borradores nunca confirmados, por autor o administrador. Los cierres confirmados se corrigen, anulan o revierten conservando historial; no se borran desde el flujo ordinario del CRM.

Octava ronda, resuelta:

- Q29. Sección «Cierres» en el CRM con dos entradas: registrar desde una oferta existente o cargar una operación histórica. La carga histórica permite buscar y vincular un inmueble existente o crear su ficha, sin exigir publicación ni captación del propietario.
- Q30. Registrar las características que tenía el inmueble al realizarse la operación. Para cierres actuales, usar la ficha vigente como punto de partida sujeto a revisión; para históricos, no atribuir automáticamente características actuales al pasado. Lo desconocido queda vacío.
- Q31. Cualquier integrante con acceso al CRM puede preparar un borrador; su autor o un administrador puede editarlo mientras no esté confirmado. Solo alguien con permiso explícito de cierres puede confirmarlo y efectuar cambios posteriores con historial.
- Q32. Cargos adicionales opcionales, con concepto, importe y moneda por cargo; admitir cargos en moneda distinta del precio base, sin convertirlos ni sumarlos al precio de cierre. Distinguir «sin cargos» de «desglose desconocido».

Novena ronda, resuelta:

- Q33. En borradores históricos, conservar el año o año/mes conocidos sin inventar día o mes. Exigir fecha completa para confirmar, conforme a los mínimos acordados, y señalar qué parte falta.
- Q34. Conservar información suficiente para comparar por zona (colonia, barrio, etc.) y precio por m²: zona estructurada, superficies de terreno y construcción separadas y, para departamentos, superficie privativa identificada expresamente; conservar precio final, moneda y superficie de referencia para derivar cocientes con nombre y unidad claros. No confundir precio total dividido entre m² de terreno/construcción con el valor aislado del suelo o de la edificación. Sin superficie conocida no se obtiene precio por m², sin impedir confirmar un cierre por los mínimos ya acordados en Q12. La consulta y comparación siguen fuera de esta entrega.
- Q35. Antes de confirmar, mostrar un resumen de inmueble, dirección, operación, fecha, precio final, características faltantes y efectos sobre la oferta vinculada. La confirmación exige una acción expresa de la persona autorizada; guardar borrador no despublica ni termina comercialización.
- Q36. Advertir al registrar un posible cierre duplicado del mismo inmueble, tipo de operación y fecha. Exigir revisar los registros existentes antes de continuar, sin fusionar ni eliminar automáticamente; una oferta ya cerrada no puede cerrarse otra vez como si fuera otra operación. Q39 precisa la excepción tras anulación y reapertura expresa. Una operación posterior distinta de un cierre real se registra por separado.

Décima ronda, resuelta:

- Q37. Guillermo elige reutilizar el flujo Google de captación: búsqueda/sugerencias, autollenado y mapa, con revisión y corrección de estado, municipio y colonia/barrio; captura manual de respaldo cuando falten datos. Sustituye la propuesta de introducir de entrada otro catálogo compartido de zonas. El flujo existente ayuda a capturar la ubicación, pero no demuestra por sí solo equivalencia de barrios ni delimita zonas de valuación. La dirección y zona históricas del cierre se conservan sin que una actualización del mapa las sobrescriba; las referencias y coordenadas temporales Google permanecen separadas conforme al ADR vigente. La procedencia y durabilidad de los campos deben quedar explícitas en el diseño técnico; confirmar una sugerencia no autoriza por sí solo almacenamiento ilimitado de datos del proveedor.
- Q38. Guillermo asigna al vendedor responsable la revisión y confirmación de los datos. No se diseñará un algoritmo para verificar dirección, zona o superficies ni para certificar su origen. Google se reutiliza como ayuda de captura. La propuesta de añadir procedencia/aproximación por cada superficie no se incorpora como requisito; el campo opcional «Referencia o notas» de Q25 sigue disponible. Se conservan las superficies separadas acordadas en Q34, los datos desconocidos y los permisos explícitos de confirmación de cierre ya acordados; esta responsabilidad humana no concede permisos adicionales.

Undécima ronda, resuelta:

- Q39. Si un cierre se anuló porque nunca ocurrió, permitir reabrir esa oferta mediante una acción expresa de alguien autorizado, con motivo y revisión de las condiciones de publicación/exclusividad. El cierre anulado conserva su historial. Un nuevo cierre se registra por separado, sin restaurar el erróneo. No reabrir al anular ni restablecer automáticamente acuerdos terminados. Para una operación nueva posterior a un cierre real, utilizar otra oferta del mismo inmueble.

Cierre de la etapa de diseño:

- Las decisiones de negocio Q1–Q39 están resueltas. La propuesta técnica identifica cada búsqueda para resolver solo la elegida, manteniendo el límite actual de un ciclo de seguimiento abierto por prospecto.
- La revisión final comprende el modelo, la migración compatible, el flujo del CRM, los efectos de confirmación/reapertura y los casos de aceptación de la [propuesta técnica](cierres-modelo-tecnico.md).
- Guillermo aprobó el diseño completo y autorizó implementar por bloques. El estado y evidencia de implementación se conservan en el informe de validación, sin reinterpretar respuestas anteriores como aceptación de producto.

Fuera del alcance de esta entrega: consulta o cálculo de comparables, valoración automática, incorporación de fuentes externas e historial de precios solicitados/anunciados y cambios de publicación.

## Registro de decisiones

Guillermo aceptó expresamente las cuatro recomendaciones de la primera ronda: «primero registro e historial, ventas y rentas separadas, operaciones propias nuevas e históricas, y cierre confirmado por un asesor autorizado». Se incorporaron al glosario cierre de operación y precio de cierre. Las recomendaciones de rondas posteriores continúan siendo propuestas hasta su respuesta.

Guillermo aceptó la segunda ronda: «todos los tipos, un mismo inmueble con operaciones independientes, permisos explícitos y correcciones con historial». Se actualizaron los términos del glosario y se registró el [ADR de identidad e historial](../adr/0002-inmueble-operaciones-historial.md). No se eligieron todavía tablas, claves ni una estrategia de migración.

Guillermo aceptó la tercera ronda: «precio base y cargos separados, las fechas propuestas, históricos incompletos como borradores y cierres con características faltantes señaladas». Se actualizaron las definiciones del glosario. La confirmación sigue siendo humana; esta decisión no añade comprobantes documentales obligatorios.

El 21 de noviembre Guillermo aceptó las recomendaciones Q13–Q16: efectos limitados a la oferta vinculada, fin de comercialización por cierre con contrato conservado, anulación con trazabilidad y coincidencias resueltas por una persona. Se incorporaron al glosario oferta de comercialización y anulación de cierre. La anulación acordada cubre errores de registro de una operación no concretada; el caso de una operación real que luego se deshace sigue abierto.

En Q17 Guillermo corrigió la recomendación de zona mínima: «Necesitamos dirección exacta». Se conserva esa exigencia sin asumir todavía que obligue a un punto GPS. Aceptó Q18–Q20: vínculo opcional con prospecto, visibilidad interna y marca manual de prueba. Un cierre con características incompletas puede confirmarse según Q12, pero la falta de dirección exacta es un dato obligatorio pendiente, no una simple característica opcional.

Guillermo aceptó Q21–Q24 el 21 de noviembre: componentes del domicilio, alternativa rural individualizada, resolución de intención mediante acción explícita y administración del permiso de cierres. Se actualizaron esas definiciones en el glosario; no se ha implementado el modelo ni cambiado permisos reales.

En Q26 Guillermo precisó: «solamente necesitamos los precios finales, es decir, el precio en el que se vendió o rentó». Esa corrección limita el historial a hechos de cierre y sus rectificaciones, no a las variaciones comerciales previas. Aceptó las recomendaciones Q27 y Q28. Tras aclarar Q25, aceptó un campo «Referencia o notas» opcional, sin documentos obligatorios.

El 22 de noviembre Guillermo aceptó Q29–Q32: sección «Cierres» con entrada desde oferta o carga histórica, características correspondientes al momento de la operación, preparación de borradores por el equipo con confirmación reservada a personas autorizadas, y cargos opcionales separados con moneda propia. Ninguna de estas decisiones se ha implementado todavía.

Al responder inicialmente Q34, Guillermo pidió considerar zona (colonia, barrio, etc.) y precio por m² para guardar información útil a futuras comparaciones. Después aceptó expresamente el ajuste de Q34 y las recomendaciones Q33, Q35 y Q36: fechas parciales solo en borradores, superficies identificadas y zona estructurada, resumen con confirmación expresa y revisión de posibles cierres duplicados. Se mantiene la separación entre datos almacenados ahora y futuras herramientas de comparación.

En Q37 Guillermo pidió «usar el mismo algoritmo que usamos cuando el cliente pone en venta su casa» y «la información de Google en el mapa». Se revisó la integración existente: `google_locations.components` propone componentes de dirección, normaliza estados y no sustituye municipio por localidad; `LocationEditingSession.choose` permite revisar/corregir y deja pendientes los campos omitidos por Google. Se reutilizará ese recorrido para capturar ubicación y zona del cierre. No se interpreta la decisión como autorización para fusionar zonas automáticamente ni para copiar resultados temporales al historial permanente. La responsabilidad de revisión se precisó en Q38.

Guillermo resolvió Q38: «confirmar estos datos es su trabajo» y «no necesitamos ningún algoritmo para esto», refiriéndose al vendedor responsable. Se cierra la rama de verificación automática y se retira la propuesta de campos adicionales de procedencia por superficie como requisito. Se mantienen la ayuda de Google, la revisión humana, las notas opcionales, la conservación de valores al cierre y las reglas de acceso ya aprobadas.

Guillermo aceptó expresamente Q39 el 22 de noviembre. La reapertura tras anulación es una acción separada, autorizada y con motivo; no borra ni restaura el cierre erróneo y no revive acuerdos de exclusividad terminados. Se incorpora esta excepción a la protección frente a cierres repetidos de Q36.

Reglas existentes que se conservan: MXN y USD, moneda explícita y sin conversión automática; venta como importe total y renta como mensualidad. El catálogo actual incluye tipos residenciales, comerciales, industriales y rurales, y excluye Temporada y Departamento Compartido. No se está aprobando aquí ampliar ese catálogo. Despublicar o retirar conserva las citas existentes y avisa al asesor si hay citas futuras, según Q20 de captación; no se añade cancelación automática.

Hechos de integración contrastados: despublicar no termina la exclusividad; retirar sí termina los acuerdos abiertos. Ninguna acción actual registra un cierre de venta/renta ni identifica por sí sola al comprador. Los vínculos de interés y las citas no acreditan quién compró o rentó. La dirección y el punto geográfico tampoco identifican por sí solos una unidad física.
