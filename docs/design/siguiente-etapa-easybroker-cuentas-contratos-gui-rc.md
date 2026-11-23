# Siguiente etapa: EasyBroker, cuentas, contratos, interfaz y RC

22 de noviembre de 2026. Entrevista de diseño solicitada por Guillermo mediante grill-with-docs. La aprobación final del diseño técnico y el punto de continuidad se registran al final. No se contratan servicios por este documento. Las rondas conservan las decisiones y correcciones; solo se crean ADR para decisiones arquitectónicas con alternativas y coste relevante de reversión.

**Estado vigente:** las decisiones EasyBroker hasta Q34 y el [diseño técnico consolidado](easybroker-modelo-tecnico.md) están aprobados por Guillermo. Implementación pendiente para un contexto nuevo. Las secciones de preguntas conservan la cronología; prevalecen las respuestas posteriores, sus correcciones y la aprobación final.

## Punto de partida confirmado

- Guillermo cerró satisfactoriamente las pruebas de resultados de venta/renta e historial, incluida captación externa y retirada, después de probar conservación de ficha, renta en teléfono y corrección de importe con correo/fecha. Ver [aceptación](../testing/cierres-y-comparables.md).
- La actualización de seguridad de Next.js a 16.4.6 quedó completada y comprobada en la etapa anterior. No equivale a una garantía de ausencia de avisos futuros.
- Cuentas: registro, acceso, enlace de verificación de email, reenvío y recuperación ya existen. El teléfono se normaliza, pero no hay desafío ni marca de posesión verificada. Ver `backend/api/capture.py`, `datalayer/models.py` y [diseño existente](cuentas-y-verificacion.md). No se verificó hoy la configuración operativa del proveedor de correo.
- Contratos: `CaptureAgreement` ya conserva versión, texto, copia comercial, aceptante y fechas. El texto sigue siendo demo y no hay catálogo administrable de plantillas. Los PDF se generan desde datos conservados; no existe archivo duradero del binario exacto emitido ni consulta directa de todas las versiones desde la interfaz. Ver `backend/datalayer/captures.py`, `capture_catalog.py`, `capture_contract.py` y `backend/api/capture.py`.
- RC mantiene como base los [acuerdos previos](acuerdos-q215-q240.md#5-criterios-de-fases): AWS, copias externas, restauración conjunta comprobada y corte con un solo entorno procesando. Producto AWS, capacidad, región y presupuesto definitivo pendientes; no se contrata por este documento.
- Credencial continua de WhatsApp y textos con Santiago conservan su aplazamiento; deben volver a revisarse al decidir operación continua.

## Evidencia EasyBroker

Documentación oficial consultada el 22 de noviembre: [introducción](https://dev.easybroker.com/docs/api-de-easybroker) y [propiedades](https://dev.easybroker.com/docs/propiedades). La API permite consultar, crear y actualizar propiedades, y registrar solicitudes de contacto. La cuenta real requiere plan de pago y clave; existe ambiente de pruebas. La clave se utiliza desde servidor.

Crear con estado publicado puede enviar también a los portales activos de la cuenta. La existencia de lectura/escritura no decide el propósito de Maia ni demuestra sincronización completa. No se han realizado escrituras ni conectado una cuenta real. Antes de diseñar intercambio hay que decidir qué sistema será responsable de cada dato y cómo se tratarán cambios, bajas, cierres y duplicados.

## Árbol de decisiones

- EasyBroker: propósito → inventario/contactos incluidos → autoridad por dato y dirección del intercambio → correspondencias/duplicados → publicación, privacidad, fallos y reconciliación → aceptación.
- Cuentas: personas incluidas → momentos de verificación → canal de prueba de posesión → número cambiado/recuperación → límites, errores y aceptación.
- Contratos: tipos incluidos → responsable del texto → versiones de plantilla y contratos emitidos → aceptación y evidencia → archivo, acceso, conservación y sustituciones.
- Interfaz: problemas prioritarios y superficies → recorridos y navegación → diseño visual y móvil → aceptación.
- RC: alcance resultante → requisitos operativos → recuperación y pérdida máxima admisible → infraestructura/presupuesto → ensayo de corte y criterios de salida.

## Ronda 1: preguntas originales

Las recomendaciones siguientes son propuestas, no acuerdos.

- Q1. ¿Qué trabajo debe resolver EasyBroker: traer inventario, publicar desde Maia, intercambiar datos en ambos sentidos o sustituir parte del CRM? Recomendación: comenzar consultando/importando inventario propio, sin publicar ni sincronizar en ambos sentidos hasta definir responsabilidades.
- Q2. ¿Las mejoras de cuentas incluyen propietarios, prospectos y equipo, o primero propietarios? Recomendación: completar propietarios reutilizando lo existente, sin exigir cuenta a quien solo busca propiedades.
- Q3. ¿El contrato definitivo es exclusivamente el de comercialización/exclusividad o también documentos de compraventa y arrendamiento? Recomendación: exclusividad primero, con plantillas versionadas, todos los acuerdos consultables y documento emitido conservado.
- Q4. ¿La prioridad de interfaz es apariencia, facilidad de uso o ambas, y en qué pantallas? Recomendación: corregir primero captación, acceso y acciones principales del CRM en móvil; después unificar el aspecto visual.

Las preguntas de sincronización, proveedor de verificación, evidencia contractual y despliegue se abrirán cuando sus decisiones previas estén resueltas. No se modifican por anticipado los flujos actuales.

## Respuestas de Guillermo y estado vigente

Guillermo acepta las recomendaciones salvo Q2, que solicita aclarar, y Q4, que aplaza expresamente para el final. La prioridad actual es EasyBroker.

- Q1 aprobada: comenzar consultando/importando inventario propio desde EasyBroker. Sin publicar ni actualizar EasyBroker en esta primera integración; no se aprueba todavía sincronización en ambos sentidos. Publicación en Maia, periodicidad y autoridad de cada dato siguen pendientes.
- Q2 pendiente: aclarar la diferencia entre cuentas de propietarios que suben inmuebles, integrantes del equipo que usan CRM y prospectos que buscan propiedades. No interpretar la aceptación general como decisión de esta pregunta.
- Q3 aprobada: empezar por comercialización/exclusividad, con plantillas versionadas, contratos históricos consultables y conservación del documento exacto emitido. No se incluye por ahora diseño de compraventa o arrendamiento.
- Q4 aplazada: diseño de interfaz al final, sin abrir preguntas visuales ahora.

## Ronda 2: preguntas originales de EasyBroker

Propuestas pendientes de respuesta:

- Q5. ¿Importar solo propiedades propias publicadas o también borradores, retiradas y operaciones pasadas? Recomendación: comenzar con las publicadas y disponibles, sin convertir estados externos en cierres confirmados.
- Q6. ¿Las propiedades importadas aparecen automáticamente en el sitio/chat de Maia o pasan por revisión inicial? Recomendación: revisión y selección inicial desde CRM antes de exponerlas.
- Q7. ¿Dónde se editan los datos de las propiedades importadas? Recomendación: EasyBroker como origen de datos del anuncio; Maia conserva atención comercial e historial propios. No permitir ediciones locales que luego se pierdan silenciosamente. La autoridad por campo y los efectos de cierre se detallarán después.
- Q8. Si el inmueble ya existe en Maia, ¿vincular expresamente o crear otro registro? Recomendación: mostrar coincidencias para decisión humana y conservar identificadores; no unir automáticamente por dirección ni sobrescribir captaciones/contratos existentes.

Periodicidad, bajas, conflictos, campos públicos/privados y recuperación de fallos se resolverán después de estas decisiones. La aclaración de Q2 queda registrada, pero su rama se retomará tras EasyBroker.

## Respuestas de ronda 2 y precisión de alcance

Guillermo acepta las recomendaciones Q5–Q8:

- Q5: primera importación de propiedades propias publicadas y disponibles; no transformar estados externos en cierres confirmados.
- Q6: revisión y selección inicial en CRM antes de exponerlas en Maia.
- Q7: los anuncios importados se actualizan en EasyBroker; atención, citas e historial comercial permanecen en Maia. El detalle de autoridad por campo continúa pendiente.
- Q8: vinculación humana cuando exista la misma propiedad en Maia, conservando identificadores, contratos e historial.

Además exige estudiar el alcance real de la API antes de cerrar el diseño. Su necesidad es importar automáticamente el inventario de una o varias cuentas autorizadas y disponer de una opción de despublicación. Importación automática y aprobación inicial para exposición pública son acciones distintas y compatibles. No se ha decidido si despublicar debe afectar solo Maia o también EasyBroker.

Guillermo aún no tiene cuenta de EasyBroker y prevé disponer de ella al salir a RC. No se le pide una credencial para diseñar ni para probar con el entorno público de demostración. La aceptación real de permisos e inventario queda pendiente hasta disponer de cuentas autorizadas, antes de declarar operativa la integración en RC.

## Investigación y prueba de API · 22 de noviembre

Evidencia y límites detallados: [investigación del alcance de EasyBroker](../research/easybroker-alcance-api-2026-11-22.md).

La referencia [GET /properties](https://dev.easybroker.com/reference/get_properties) habla de la organización; la [autenticación](https://dev.easybroker.com/docs/autenticaci%C3%B3n) usa una clave única por cuenta obtenida por un administrador. El correo no sustituye esa autorización. Conectar varias cuentas se plantea como conexiones independientes con sus propias credenciales; es una propuesta de diseño, no una prueba ejecutada con cuentas reales.

Existe una modalidad separada [para partners](https://dev.easybroker.com/docs/introducci%C3%B3n), cuyos listados reciben propiedades de agencias conectadas a esa aplicación. No equivale a acceso indiscriminado a la bolsa ni se presume disponible con una suscripción común. No se elige esa modalidad para Maia por este hallazgo.

Se realizaron únicamente tres GET contra `api.stagingeb.com` con la clave pública de pruebas de la documentación: listado paginado, detalle de un registro y listado con filtro `published`; los tres devolvieron 200. El listado de prueba mostró paginación y el detalle mostró operaciones, imágenes, ubicación y datos privados. Las respuestas muestreadas no incluyeron `status`; no inferir su presencia al diseñar bajas o reconciliación. No se modificaron propiedades ni se usaron datos reales. Estos resultados no prueban permisos ni cobertura de varias cuentas de producción.

## Ronda 3: decisiones pendientes

La prueba se amplió a cuatro consultas: `/listing_statuses` ordinario también devolvió 200 con identificadores, estado y fecha de actualización, incluidos ejemplos publicados/no publicados. Su [referencia oficial](https://dev.easybroker.com/reference/get_listing-statuses) delimita el alcance a la organización. El diseño podrá estudiar este recurso para reconciliar estados sin depender de un campo ausente en el detalle; las eliminaciones definitivas y los permisos reales siguen sin comprobarse.

- Q9. ¿Las varias cuentas son fuentes de inventario para esta misma inmobiliaria, incluidas cuentas de colaboradores, o Maia atenderá inmobiliarias independientes como clientes separados? Recomendación: una sola inmobiliaria operadora en esta etapa, admitiendo varias fuentes expresamente autorizadas, sin abrir un producto para varias inmobiliarias.
- Q10. ¿Despublicar debe ocultar la propiedad solo de Maia o también modificar EasyBroker? Recomendación: solo sitio y recomendaciones de Maia, conservando ficha/historial y una exclusión que ninguna importación posterior levante automáticamente. No modificar EasyBroker en esta primera integración.
- Q11. ¿Cada cuánto actualizar el inventario automáticamente? Recomendación inicial: cada 15 minutos, más actualización manual; es un objetivo propuesto sujeto a volumen y límites comprobados, no una promesa de tiempo real ni un SLA del proveedor.

Los fallos de actualización, bajas externas, desconexión de una fuente y retención de datos de colaboradores se detallarán después de resolver alcance y responsabilidad de publicación.

## Respuestas de ronda 3

- Q9 aprobada y precisada: una misma Maia puede conectar simultáneamente las cuentas autorizadas de Santiago, Guillermo y otros socios e importar inventario desde todas ellas. Son varias fuentes para esta operación; no se ha solicitado separar clientes inmobiliarios ni sus CRM. Se conserva el filtro Q5 de propiedades publicadas y disponibles y la revisión inicial Q6.
- Q10 aprobada: despublicar solo en Maia, conservando ficha/historial y una exclusión persistente que no levanta una importación posterior. La primera integración no modifica EasyBroker.
- Q11 modificada y aprobada: actualización automática **cada hora**, más la opción de actualizar manualmente. La propuesta de 15 minutos queda sustituida. No se promete reflejar cambios externos en tiempo real.

## Ronda 4: decisiones pendientes

- Q12. ¿Qué hacer cuando EasyBroker confirme que una propiedad dejó de estar disponible o publicada? Recomendación: ocultarla automáticamente del sitio y recomendaciones de Maia al detectarlo, conservar ficha/historial y mostrar el motivo; no confirmar cierres ni inventar precio final.
- Q13. ¿Qué hacer si falla una actualización de una cuenta? Recomendación: aislar el fallo, continuar con las otras fuentes, avisar en CRM y conservar temporalmente el último inventario válido sin presentarlo como actualizado. Una consulta fallida o incompleta no acredita una baja. Si se acepta esta política, falta decidir el plazo máximo de información sin renovar.
- Q14. ¿Quién recibe los prospectos de una propiedad importada? Recomendación: asignar un asesor responsable del CRM por cuenta conectada, con posibilidad de cambiarlo por propiedad. La cuenta fuente y el asesor local son conceptos distintos; no crear ni cambiar permisos por coincidencia de email.
- Q15. ¿Una importación debe repetir el formulario del propietario y generar un contrato nuevo? Recomendación: no exigir recaptura ni generar contratos por el hecho de importar. Conservar procedencia y responsable; las condiciones/documentos de comercialización se tratarán expresamente, sin inferir titularidad, exclusividad o autorizaciones del simple acceso API.

Siguen pendientes el plazo ante fallos, reaparición en origen, duplicados entre fuentes, datos públicos/privados, fotos, efectos de desconectar una cuenta y los criterios de aceptación de la sincronización. Su detalle dependerá de las respuestas anteriores.

## Respuestas de ronda 4

Guillermo acepta Q12–Q15 y enfatiza que conservar la ficha es **muy importante**:

- Q12: al detectar una baja o indisponibilidad confirmada en EasyBroker, ocultar automáticamente la oferta del sitio y recomendaciones de Maia, manteniendo ficha, procedencia, motivo e historial. No borrar el registro ni convertir la baja en cierre, precio final o fecha de operación.
- Q13: un fallo de una cuenta no detiene las demás; avisar en CRM y conservar temporalmente su último inventario válido. Una respuesta fallida/incompleta no acredita una baja. El plazo máximo sigue pendiente.
- Q14: asesor responsable del CRM por cuenta de origen, modificable por propiedad; sin conceder permisos ni crear cuentas automáticamente por email.
- Q15: importar no exige repetir captación ni genera un contrato automáticamente. Conservar procedencia y responsable; la documentación comercial tiene tratamiento separado.

## Ronda 5: decisiones pendientes

- Q16. ¿Cuánto tiempo seguir ofreciendo inventario cuya actualización falla? Recomendación: hasta 24 horas desde la última comprobación válida de disponibilidad de cada oferta. Avisar desde el primer fallo; al superar ese plazo, ocultar automáticamente conservando ficha/historial. Un éxito parcial no renueva la vigencia de toda la cuenta. El plazo es una propuesta de producto, no una garantía del proveedor.
- Q17. ¿Republicar automáticamente una oferta que EasyBroker vuelve a mostrar disponible? Recomendación: dejarla pendiente de revisión para republicar. Una despublicación manual en Maia, un cierre propio o una retirada local nunca se levantan por actualizar el origen.
- Q18. Tras vincular humanamente la misma propiedad de varias cuentas, ¿qué anuncio gobierna precio, texto y fotos? Recomendación: elegir una fuente principal por oferta, conservar las otras vinculaciones y no mezclar valores ni cambiar a otra fuente automáticamente cuando falle la principal.
- Q19. ¿La conservación de ficha debe incluir fotos importadas o solo sus enlaces externos? Recomendación: conservar copias de las fotografías autorizadas para uso en Maia junto con la ficha; no depender solo de enlaces que pueden desaparecer. No importar automáticamente adjuntos privados. Falta especificar permisos, almacenamiento, cambios y eliminación de medios.

Los escenarios de desconexión de cuenta, recuperación tras fallos, privacidad de publicación y medios se completarán a partir de estas respuestas; el diseño sigue abierto y no se implementa todavía.

## Respuestas de ronda 5

- Q16 aprobada: avisar desde el primer fallo y permitir exposición hasta 24 horas desde la última comprobación válida de cada oferta. Después ocultarla sin borrar ficha ni historial. No renovar ese plazo por un éxito parcial ajeno a la oferta.
- Q17 aprobada: una oferta que reaparece disponible en origen queda pendiente de revisión para republicar. Nunca levantar automáticamente una despublicación manual, retirada o cierre local.
- Q18 aprobada: fuente principal elegida por oferta cuando haya varias vinculaciones; no mezclar datos ni sustituirla automáticamente ante fallos.
- Q19 corregida por Guillermo: **no es necesario conservar las imágenes**. La conservación exigida se aplica a los datos de la ficha y su historial, sin archivo permanente de las fotografías importadas. No implementar la propuesta anterior de guardar copias duraderas. La decisión no elimina fotos propias de captación ni decide por sí sola cómo se muestran las imágenes de anuncios vigentes. Se mantiene fuera de la importación inicial la incorporación automática de adjuntos privados.

## Ronda 6: decisiones pendientes

- Q20. ¿Qué ocurre al desconectar expresamente una cuenta de origen? Recomendación: detener sus importaciones y ocultar las ofertas cuya fuente principal sea esa cuenta; conservar datos, historial y vinculaciones, sin pasar automáticamente a una fuente alternativa. La reconexión conserva las exclusiones manuales y deja las ofertas ocultadas pendientes de revisión antes de republicar.
- Q21. ¿Qué información privada de EasyBroker puede aparecer en el sitio o en respuestas del chat? Recomendación: dirección exacta y notas privadas solo en CRM; al público, ubicación aproximada y datos comerciales autorizados. Las restricciones de ocultar ubicación o precio del origen se respetan como mínimo. Disponer del dato en API no autoriza a publicarlo.
- Q22. ¿Hay que revisar cada cambio de un anuncio ya aprobado? Recomendación: aplicar automáticamente cambios habituales de precio, descripción y características, conservando historial y sin levantar bloqueos locales; cambios de dirección o tipo de operación requieren revisión y mantienen la oferta fuera del sitio/chat hasta aprobarlos. Una moneda distinta se conserva explícita sin conversión automática. La política de restricciones de privacidad se aplica al recibir cambios.

Después se concretarán validación de campos, presentación de fotos vigentes sin archivo histórico, desconexión/reconexión y aceptación integral. No se inicia la implementación durante la entrevista.

## Respuestas de ronda 6

Guillermo aprueba Q20–Q22:

- Q20: desconectar una cuenta detiene sus importaciones y oculta las ofertas que la tienen como fuente principal. Se conservan ficha, historial y vinculaciones, sin cambiar automáticamente a otra fuente. La reconexión no levanta exclusiones manuales y exige revisar antes de republicar las ofertas ocultadas por desconexión.
- Q21: dirección exacta y notas privadas solo para CRM. Sitio y chat usan ubicación aproximada y datos autorizados, respetando como mínimo las restricciones de ocultar ubicación o precio del origen. No basta con que un campo esté disponible en la API para hacerlo público.
- Q22: cambios habituales de precio, descripción y características se actualizan automáticamente con historial. Cambios de dirección o tipo de operación requieren revisión y despublicación hasta aprobarlos. Nunca levantar una despublicación manual ni convertir monedas automáticamente. Las restricciones de privacidad se aplican también al actualizar.

## Ronda 7: decisiones pendientes

- Q23. Si una oferta se ocultó únicamente por superar 24 horas sin actualización, ¿puede reaparecer al recuperarse la conexión? Recomendación: sí, únicamente si antes estaba aprobada/publicada y se comprueban disponibilidad, ausencia de cambios que requieren revisión y ausencia de bloqueo local. Esta excepción no aplica a baja en origen (Q17), desconexión expresa (Q20), retirada, cierre ni despublicación manual. Si se acepta, el estado debe conservar el motivo exacto de ocultación para distinguir estos casos.
- Q24. Si EasyBroker exige ocultar el precio, ¿admitir el anuncio en Maia sin importe público? Recomendación: sí, mostrar Precio por consultar y permitir interés/contacto, sin revelar el importe en sitio ni chat. No afirmar que cumple un presupuesto por conocer un precio privado; la precisión de filtros se definirá sin exponerlo. El importe disponible para el equipo permanece privado.
- Q25. ¿Qué hacer con un registro incompleto? Recomendación: conservarlo y señalar faltantes. Sin operación identificable, tipo de inmueble o ubicación pública mínima de municipio/zona, no publicarlo hasta corregir su origen. Características desconocidas, superficies y fotografías no se inventan ni se convierten a cero. Precio oculto por decisión del origen se trata según Q24, no como un cero ni como permiso para exponerlo. El catálogo de tipos y casos de ubicación se comprobará contra muestras antes de cerrar el contrato técnico.

El modelo ya acordado de inmueble físico con ofertas de venta/renta independientes se aplicará también a importaciones con más de una operación. No se agregan cierres por descubrir esas operaciones. La correspondencia de campos, ausencias, fuentes y estados se documentará en el diseño técnico después de resolver las decisiones de producto.

## Respuestas de ronda 7 y aclaración de Q24

- Q23 aprobada: recuperar automáticamente la exposición solo si la causa exclusiva fue caducidad de las 24 horas sin comprobación, la oferta estaba aprobada/publicada y una consulta válida confirma que sigue disponible y no requiere revisión. No elimina otras causas de bloqueo.
- Q25 aprobada: conservar registros incompletos, señalar faltantes y no publicar sin los mínimos acordados; no inventar valores ni exigir fotos para conservar la ficha.
- Q24 pendiente: Guillermo pregunta por qué se ocultaría el precio. No interpretar su aceptación del resto como aprobación de esta pregunta.

La [referencia oficial de actualización](https://dev.easybroker.com/reference/patch_properties-property-id) documenta `show_prices`, opción del anuncio para mostrar u ocultar sus precios. No se propone ocultar precios de anuncios que los muestran. La regla de respetar restricciones del origen ya está acordada en Q21; Q24 decide si un anuncio con precio oculto puede presentarse en Maia como Precio por consultar o queda fuera del inventario público hasta que el anunciante haga público el precio. Recomendación: permitir Precio por consultar. No se atribuye al anunciante un motivo concreto para activar esa opción ni se afirma que todas las propiedades la usen.

## Resolución de Q24

Guillermo acepta mostrar **Precio por consultar** cuando el anuncio de origen tiene el precio oculto. El importe privado no se revela en sitio ni chat. Los precios públicos se muestran normalmente. Esto no aprueba todavía cómo participan estos anuncios en filtros numéricos de presupuesto.

## Ronda 8: decisiones pendientes

- Q26. ¿Incluir precios ocultos como coincidencias de una búsqueda con presupuesto? Recomendación: no incluirlos en los resultados filtrados por importe ni afirmar que encajan en el presupuesto usando el dato privado. Podrán consultarse cuando no haya filtro de precio y, si se ofrecen como alternativas, quedarán separados como Precio por consultar, sin afirmar compatibilidad de importe. Así no se revela indirectamente el precio oculto mediante búsquedas repetidas.
- Q27. Si el origen retira expresamente un dato antes conocido, ¿conservar el valor anterior como información vigente? Recomendación: conservarlo en el historial y mostrar el dato actual como desconocido. Si pierde un mínimo obligatorio, dejar pendiente de revisión. La mera omisión de un campo en una respuesta parcial no prueba su retirada; una consulta fallida o incompleta conserva el tratamiento Q13, y se comprobarán las reglas del proveedor al definir el contrato técnico.
- Q28. ¿Quién puede conectar, cambiar la credencial o desconectar cuentas de origen? Recomendación: administradores existentes del CRM; el uso diario del inventario y el registro de resultados siguen disponibles al equipo, sin otro permiso adicional. Toda modificación de una conexión conserva autor y fecha; las credenciales nunca se muestran al público, al chat ni en el historial comercial.

Continúan pendientes los casos especiales del proveedor, la forma de usar fotografías vigentes sin archivo permanente y la validación integral con varias cuentas. La etapa sigue siendo diseño; no se ha implementado la integración.

## Respuestas de ronda 8

Guillermo aprueba Q26–Q28:

- Q26: las ofertas con precio oculto no se incluyen como coincidencias en resultados filtrados por importe ni se presentan como compatibles con un presupuesto mediante el precio privado. Se admiten en consultas sin filtro de importe; cualquier alternativa debe distinguirse como Precio por consultar.
- Q27: un dato retirado expresamente del origen deja de presentarse como vigente; su valor previo permanece en el historial. Si pierde un mínimo requerido, la oferta queda pendiente. Una omisión de una respuesta parcial o un error no acredita esa retirada.
- Q28: solo administradores existentes gestionan las conexiones y sus credenciales. Se registra autor y fecha, sin almacenar secretos en el historial comercial. El trabajo diario del equipo no requiere un permiso adicional de importación.

## Estado de la entrevista

EasyBroker es la prioridad y la integración sigue sin implementarse. Se comprobarán diferencias entre tipos de operación, periodicidades, monedas y tipos de inmueble antes de definir excepciones de importación. Permanecen por resolver el tratamiento de medios vigentes y de citas existentes cuando una oferta deja de estar disponible; después se consolidarán el contrato de datos, los estados y las pruebas de aceptación.

## Ronda 9: decisiones pendientes

- Q29. ¿Qué hacer con operaciones cuyo importe no se puede representar correctamente en la búsqueda actual de Maia, por ejemplo precio por m²/hectárea, renta temporal o monedas distintas de MXN/USD? Recomendación: conservar el registro de origen con unidad, periodicidad y moneda explícitas, y señalarlo como pendiente de compatibilidad, sin exponerlo como una oferta de precio total o mensual. Publicar inicialmente solo las operaciones representables sin inventar una conversión. Tipos de inmueble sin correspondencia clara también quedan pendientes; no se fuerzan a otro tipo ni se descarta su ficha. La ampliación a esos formatos requeriría otra decisión de alcance.
- Q30. ¿Qué sucede cuando una fotografía externa no carga o el anuncio no tiene fotos utilizables? Recomendación: mantener disponible la información comercial aprobada con una imagen de sustitución neutra o sin fotografía, sin generar imágenes del inmueble ni ocultar toda la oferta por una foto fallida. Las fotos vigentes se usan sin archivo histórico propio; la solución técnica debe respetar privacidad y permisos del origen. No afecta las reglas de fotografías de captaciones propias.
- Q31. Si una oferta deja de estar disponible y tiene citas futuras, ¿se cancelan automáticamente? Recomendación: conservar citas e historial, avisar internamente al asesor y evitar nuevas citas para esa oferta mientras no esté disponible. El asesor confirma con el cliente los cambios; la importación no cancela citas ni envía mensajes externos por sí sola.

La compatibilidad inicial propuesta en Q29 no cambia las monedas o tipos ya admitidos en captación propia. No se debe copiar una cifra sin su unidad, presentar moneda oculta como MXN por defecto ni inferir precio final a partir de un anuncio.

## Respuestas de ronda 9

Guillermo aprueba Q29–Q31:

- Q29: conservar registros con precio por superficie, modalidades de renta no representables, monedas o tipos sin correspondencia inequívoca, indicando unidad y datos de origen, pendientes de compatibilidad y sin publicación incorrecta. No convertir ni clasificar por suposición.
- Q30: la falta o fallo de fotografías externas no oculta por sí solo una oferta aprobada. Mostrar información sin esa imagen o con presentación neutra, sin inventar imágenes ni archivar fotos históricas. No cambia la captación propia.
- Q31: conservar citas existentes y avisar internamente al asesor al perder disponibilidad. No aceptar nuevas citas para la oferta no disponible. La importación no cancela visitas ni envía mensajes externos automáticamente.

## Ronda 10: decisiones pendientes antes de consolidar

- Q32. ¿Cómo atribuir cambios automáticos si no hay una persona con sesión ejecutando el cambio? Recomendación: identificar Sincronización EasyBroker, cuenta de origen, fecha y valores anteriores/nuevos. No atribuirlos falsamente al correo del titular de la cuenta. Las acciones humanas, incluida una actualización manual, conservan el correo de sesión del iniciador; si ejecuta después un proceso, distinguir iniciador y mecanismo de actualización. Credenciales fuera del historial.
- Q33. ¿Qué hacer si el texto libre incluye una dirección exacta o un precio que debe estar oculto? Recomendación: revisión humana de la descripción antes de exponerla y después de cada cambio de texto, con una versión pública aprobada separada del texto de origen. Esto ajusta Q22: precios y características estructuradas compatibles siguen actualizándose automáticamente, pero el texto nuevo no reemplaza automáticamente la descripción pública. Conservar el texto público anterior solo si sigue siendo compatible con las restricciones actuales; si cambian para restringir precio/ubicación y no se ha validado su cumplimiento, ocultar la oferta hasta revisar. No prometer detección automática infalible de datos privados ni enviar texto sin aprobar al chat.
- Q34. ¿Qué evidencia debe exigirse para declarar operativa la integración? Recomendación: desarrollo y pruebas ahora con datos ficticios y fallos controlados; antes de cerrar su aceptación en RC, una prueba con al menos dos cuentas reales autorizadas, preservación de procedencia, reimportación sin duplicados, exclusiones persistentes, bajas, revisión, aislamiento de fallos y autoría. La integración de varias cuentas reales queda pendiente si solo se prueba una. No es necesario abrir esas cuentas durante esta entrevista ni probar fallos destructivos en producción.

Después de estas respuestas se consolidará un diseño técnico de EasyBroker con proyecciones pública/privada, correspondencia de ofertas, estados de sincronización/publicación, identidad de fuentes, conservación y pruebas, antes de solicitar confirmación del diseño completo. Cuentas, contratos definitivos, interfaz y despliegue conservan sus ramas separadas del plan.

## Respuestas de ronda 10

Guillermo aprueba Q32–Q34 y pide avanzar al diseño técnico:

- Q32: los cambios automáticos identifican proceso, cuenta, ejecución, fecha y diferencias. Las acciones humanas conservan el correo de sesión; una actualización manual distingue iniciador y proceso que aplica sus resultados. No se atribuye la ejecución al dueño de la cuenta externa.
- Q33: texto público revisado y separado del origen; la descripción nueva espera aprobación. Esto sustituye la actualización automática de texto propuesta en Q22. Precios y características estructuradas continúan actualizándose conforme a sus reglas y restricciones de privacidad. No exponer una versión anterior si dejó de ser compatible.
- Q34: desarrollar y probar con datos ficticios ahora; antes de cerrar la aceptación de la integración en RC, comprobar al menos dos cuentas reales autorizadas, sin duplicados, con exclusiones persistentes, bajas, historia, procedencia y fallos aislados. No se necesitan credenciales reales para elaborar el diseño.

Documento resultante: [EasyBroker: modelo técnico](easybroker-modelo-tecnico.md). Las decisiones funcionales aprobadas no implican que se hayan implementado ni que se haya aprobado todavía el conjunto de propuestas técnicas. La siguiente etapa de producto es revisar ese diseño; no se realizan migraciones ni conexiones reales por elaborarlo.

## Aprobación final y continuidad · 22 de noviembre de 2026

Guillermo respondió: «De acuerdo con el diseño técnico. Regístralo como aprobado, actualiza tu memoria, y comenzaré con la implementación de EasyBroker en un contexto nuevo».

El diseño técnico queda **aprobado y sin implementar**, sustituyendo el estado previo de propuesta. La implementación continuará desde la sección 11 del modelo técnico, preservando los cambios previos del repositorio. No se inicia en este cierre, no se conectan cuentas reales ni se ejecutan cambios de Git. La aceptación de RC sigue requiriendo pruebas con al menos dos cuentas reales autorizadas. Los demás frentes mantienen su alcance y aplazamientos.
