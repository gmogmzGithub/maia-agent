# Sexto incremento: captación de propiedades

Fecha: 7 de noviembre de 2026.

Estado: alcance confirmado por Guillermo tras cinco rondas; añadió Preventa y autorizó continuar. Implementación en código y validación técnica completadas según [el plan](plan-sexto-incremento.md); instancia Docker local actualizada, con aceptación manual y correo real pendientes. Guillermo priorizó este incremento mientras Meta aprueba las plantillas del cuarto. El incremento 5 queda pospuesto. La [guía de validación](../testing/sexto-incremento.md) registra evidencia técnica y pendientes manuales.

## Alcance acordado

Pendientes de producto registrados tras la prueba de Guillermo: mejorar el diseño de captación y la forma de pedir crear cuenta. El flujo completo de cuentas y verificación real de celular y correo se abordará en [otra etapa](cuentas-y-verificacion.md). La [validación del incremento](../testing/sexto-incremento.md) distingue la prueba local exitosa de los recorridos todavía pendientes.

Según Q231 y Q240 de los [acuerdos de diseño](acuerdos-q215-q240.md):

1. El propietario envía un formulario con su propiedad para venta o renta y el precio solicitado.
2. El equipo revisa la solicitud desde el CRM antes de incorporarla al inventario.
3. El propietario puede marcar «Solicitar una opinión de valor».
4. Santiago o el asesor designado revisa, registra y comunica esa opinión. La primera versión no calcula una valoración automática.

El envío del formulario no publica la propiedad ni acredita su titularidad. Los datos del propietario permanecen privados, conforme a Q243.

### Modelo comercial confirmado el 7 de noviembre

Guillermo pidió replicar casi todo el recorrido del video, excluyendo el cobro al propietario por subir la propiedad. No habrá selección de planes ni checkout de publicación.

El modelo de captación exige exclusividad de comercialización para la inmobiliaria en todas las operaciones admitidas, incluidas venta y renta. La condición se explica desde el formulario y se formaliza después de revisar el inmueble, antes de publicarlo. No se interpreta el envío de datos como evidencia de un acuerdo ya formalizado. La exclusión del cobro por subir el inmueble no define comisiones por cierre de operación.

### Primera ronda aceptada

Guillermo aceptó las recomendaciones Q1, Q3 y Q4 y precisó Q2:

- **Q1:** explicar la exclusividad desde el formulario y formalizarla después de revisar el inmueble, antes de publicar.
- **Q2:** exigir exclusividad en cualquiera y todas las opciones; en el alcance actual, venta y renta.
- **Q3:** aceptar propietarios y representantes autorizados. El equipo verifica su relación con el inmueble antes de publicar. No se abre un canal independiente para asesores externos.
- **Q4:** incluir fotos y planos como archivos, y videos y recorridos 360 mediante enlaces. Cantidades, formatos y tamaños quedan por definir.

### Segunda ronda aceptada

Guillermo aceptó Q5, Q6, Q7 y Q10, y precisó Q8 y Q9:

- **Q5:** registrar asesor responsable, fecha de verificación del propietario o representante, referencia del acuerdo y fechas de vigencia de la exclusividad. La propuesta inicial de duración por acuerdo queda sustituida, para el contrato dummy de esta etapa, por seis meses según Q15.
- **Q6:** permitir guardar, salir, retomar y consultar solicitudes. Falta definir acceso y edición posterior al envío.
- **Q7:** dirección exacta privada y ubicación pública aproximada por defecto; el equipo puede autorizar ubicación exacta antes de publicar.
- **Q8:** cinco fotos mínimas como requisito. La plataforma acepta imágenes de tamaños amplios y reduce automáticamente peso y dimensiones para el website; no exige que el propietario las comprima previamente. No se conserva el límite propuesto de 10 MB por foto como regla de producto. Los planos, videos y recorridos 360 son opcionales. Se mantienen las propuestas aceptadas no contradichas: hasta 20 fotos (ajuste confirmado el 15 de noviembre de 2026), cinco planos de hasta 20 MB cada uno y elección de portada y orden. Falta precisar si el mínimo se exige al enviar o al publicar y los formatos que debe cubrir la conversión. Los límites internos de procesamiento deben impedir fallos de recursos sin trasladar al usuario la preparación habitual de imágenes ni prometer tamaños ilimitados.
- **Q9:** incluir todas las opciones del video, en lugar de limitar tipos y operaciones al inventario actual. El catálogo debe extraerse de las opciones visibles; si un menú no se despliega, pedir únicamente la lista que falta. Los demás campos mínimos recomendados se conservan: nombre, celular, relación con el inmueble, operación, tipo, ubicación y precio solicitado; email, descripción y características opcionales, sujeto a lo que requiera el mecanismo de acceso por definir.
- **Q10:** asignar al asesor predeterminado del CRM, notificar por Telegram y permitir reasignación. Un fallo del aviso conserva la solicitud.

La reducción automática debe conservar orientación y legibilidad y generar imágenes aptas para la galería del website. Los valores técnicos de conversión y almacenamiento se definirán durante el diseño técnico; todavía no hay implementación ni formatos verificados.

### Tercera ronda: respuestas recibidas

- **Q11:** replicar el flujo del video: datos principales y ubicación, características y precio, multimedia, comodidades, vista previa y envío a revisión. Excluir planes y cobros. Las cinco fotos se requieren para completar multimedia y enviar; guardar y salir permite un borrador incompleto.
- **Q12:** se recibieron cinco capturas con el catálogo de tipos y subtipos, transcrito abajo. Si un tipo no tiene subtipos en las capturas, no se inventan. Temporada queda expresamente excluida; se conserva Venta y Renta. Q17 completa el filtro de tipos.
- **Q13:** cuenta obligatoria con email y teléfono para publicar. No basta una solicitud anónima con contacto declarado. Q18 completa autenticación y momento del registro; falta definir verificación de contacto.
- **Q14:** aceptada en la cuarta ronda: edición libre de borradores y cambios posteriores mediante el asesor.
- **Q15:** preparar contrato dummy de exclusividad por seis meses. Q19 y Q20 completan aceptación, inicio y vencimiento. El dummy sirve para probar el recorrido y no se presenta como contrato listo para operación real.
- **Q16:** ampliar cobertura más allá de Guadalajara y zona metropolitana, manteniendo esa región como base. El código y los filtros deben admitir propiedades de otras ubicaciones aprobadas por el equipo; no conservar una lista cerrada de cuatro municipios como validación universal. Q21 confirma cobertura nacional.

### Cuarta ronda aceptada

Guillermo precisó Q17 y aceptó las demás recomendaciones:

- **Q17:** excluir Departamento Compartido. Admitir los demás tipos del catálogo, incluidos comerciales, industriales y rurales. Solo Venta y Renta; sin Temporada.
- **Q18:** cuenta con email, teléfono y contraseña. El registro se pide al guardar o enviar por primera vez; se permite comenzar a llenar el formulario antes de registrarse. Al registrarse, conservar el contenido ya ingresado.
- **Q14:** el propietario edita libremente sus borradores. Después del envío, los cambios pasan por el asesor; no modifica directamente una propiedad publicada.
- **Q19:** después de aprobar el inmueble, el propietario o representante autorizado visualiza y acepta explícitamente el dummy desde su cuenta. Registrar versión y fecha de aceptación. Los seis meses comienzan al aceptar; después el equipo puede publicar. Registrar la publicación no sustituye la aceptación.
- **Q20:** al vencer o cancelar la exclusividad, despublicar y avisar al responsable. Conservar historial y citas, sin cancelarlas automáticamente. No renovar automáticamente.
- **Q21:** admitir solicitudes de todo México. Mantener Guadalajara y zona metropolitana como base y exigir aprobación del equipo para publicar fuera de ella, además de la revisión general ya acordada.

### Quinta ronda aceptada

Guillermo aportó la captura de Q25 y aceptó las demás recomendaciones:

- **Q22:** verificar email antes de enviar la solicitud. Pedir confirmación del teléfono escrito, sin SMS en este incremento; esa confirmación no acredita posesión del número.
- **Q23:** conservar las opciones repetidas como tipo y subtipo del referente y tratarlas como equivalentes al buscar. No duplicar propiedades por esas equivalencias.
- **Q24:** admitir MXN y USD, mostrar siempre la moneda y no convertir automáticamente. El inventario preexistente conserva MXN.
- **Q25:** campo opcional de conservación con las seis opciones exactas de la captura: Excelente, Bueno, Regular, Malo, Remodelado y Para remodelar. Antigüedad y En construcción son campos separados.
- **Q26:** el propietario solicita retirada o renovación desde su cuenta y el asesor registra la resolución. Renovar requiere una nueva aceptación explícita; no hay renovación automática.
- **Q27:** aplicar cuenta y exclusividad del nuevo recorrido a captaciones nuevas. Conservar el comportamiento del inventario existente, sin exigirle regularización retroactiva.

### Recorrido consolidado

1. Comenzar formulario con los pasos del video, sin Temporada, Departamento Compartido, planes ni cobros.
2. Registrar cuenta con email, teléfono y contraseña al guardar o enviar por primera vez, conservando lo ingresado.
3. Completar información del inmueble y al menos cinco fotos optimizadas por la plataforma. Planos, videos y recorrido 360 opcionales; borradores incompletos permitidos.
4. Verificar email, confirmar el teléfono escrito y enviar a revisión. Asignar responsable y avisarle por Telegram.
5. Revisar inmueble, representación, ubicación y datos en CRM. Solicitar o registrar correcciones mediante el asesor.
6. Tras aprobación, presentar el contrato dummy para aceptación explícita desde la cuenta. Guardar versión, fecha e inicio de seis meses de vigencia.
7. El equipo publica. El contacto del propietario y la dirección exacta permanecen privados salvo autorización del equipo para la ubicación exacta.
8. Retiradas y renovaciones se solicitan desde la cuenta y las resuelve el asesor. Al vencer o registrarse cancelación, despublicar y avisar, preservando historial y citas.

Alcance nacional, con Guadalajara y zona metropolitana como base. Las captaciones nuevas cumplen este recorrido; el inventario anterior conserva su funcionamiento.

### Confirmación y Preventa

Guillermo confirmó todo el alcance y pidió agregar Preventa. Se incorpora como condición de comercialización de Venta; puede coexistir con el tipo de inmueble, la conservación y la antigüedad. Temporada permanece excluida.

### Catálogo aportado en las capturas

Catálogo aportado de 20 tipos: se admiten 19 y se excluye Departamento Compartido según Q17. Solo Venta y Renta. Se conservan las opciones repetidas de tipo y subtipo con equivalencia de búsqueda según Q23.

| Tipo | Subtipos |
| --- | --- |
| Departamento | Apartamento de campo; Apartamento de ciudad; Apartamento de playa; Departamento Loft; Departamento PentHouse; Minidepartamento |
| Bodega comercial | Sin subtipos |
| Casa | Casa de campo; Casa de ciudad; Casa de playa; Casa en condominio; Casa en quinta |
| Casa en condominio | Sin subtipos |
| Casa con uso de suelo | Sin subtipos |
| Departamento Compartido, excluido | No se ofrece |
| Dúplex | Sin subtipos |
| Edificio | Edificio comercial; Edificio residencial |
| Huerta | Sin subtipos |
| Inmueble productivo urbano | Sin subtipos |
| Local Comercial | Sin subtipos |
| Local en centro comercial | Sin subtipos |
| Nave industrial | Sin subtipos |
| Oficina | Sin subtipos |
| Quinta | Sin subtipos |
| Rancho | Sin subtipos |
| Terreno / Lote | Terreno comercial; Terreno campestre; Terreno de playa; Terreno eriazo; Terreno industrial; Terreno residencial |
| Terreno comercial | Sin subtipos |
| Terreno industrial | Sin subtipos |
| Villa | Sin subtipos |

Se conservan las etiquetas de tipos y subtipos repetidos del referente. «Casa en condominio» como tipo y como subtipo se trata como equivalente al buscar, al igual que Terreno comercial y Terreno industrial. No se crean propiedades duplicadas.

### Texto dummy de exclusividad

Texto de demostración para el recorrido. Se acepta desde la cuenta después de la aprobación del inmueble; la vigencia empieza en esa aceptación:

> DEMOSTRACIÓN. El propietario o su representante autorizado otorga a la inmobiliaria la exclusividad para comercializar el inmueble identificado en esta solicitud, mediante la operación de venta o renta seleccionada, durante seis meses desde la fecha de aceptación registrada. La inmobiliaria revisa el inmueble y la representación antes de autorizar su publicación. Subir la propiedad no genera un cobro por publicación. La exclusividad no se renueva automáticamente; al vencer o registrarse su cancelación, la propiedad deja de publicarse. Este texto es un dummy para probar el flujo y no se utiliza como contrato definitivo.

El texto no define comisiones ni condiciones de cancelación anticipada. Esas condiciones no se inventan por replicar un portal.

## Propuesta del recorrido

Los detalles siguientes son una propuesta de diseño salvo los acuerdos explícitos de las rondas aceptadas y el alcance previo.

### Website

- Acceso visible «Vende o renta tu propiedad» desde la navegación.
- Formulario con operación, tipo de inmueble, ubicación, precio solicitado, características, descripción, fotografías y datos de contacto del propietario.
- Opción independiente para solicitar una opinión de valor.
- Confirmación de recepción con referencia de solicitud. No prometer publicación ni una fecha de contacto.
- Ante un error, conservar los datos y permitir reintentar sin duplicar la solicitud.

### CRM

- Sección «Captación» con solicitudes recibidas, responsable y estado de revisión.
- Ficha privada con datos originales, contacto y notas del equipo.
- Revisión con resultado: pendiente, incorporada o descartada. Registrar quién tomó la decisión y cuándo.
- Incorporación única a una propiedad en borrador; el equipo revisa la ficha y usa la publicación existente.
- Conservar el vínculo entre solicitud y propiedad para impedir duplicados al repetir la acción.
- Si se pidió opinión de valor, permitir registrar importe, comentarios y si se comunicó al propietario. Guardar la opinión no acredita su comunicación.

Enviar una propiedad no concede seguimiento de prospección ni crea un ciclo de 28 días. La solicitud de contacto se atiende como captación, sin modificar permisos de otras conversaciones con el mismo teléfono.

## Decisiones por concretar

### Referencia en video y entrevista de diseño

Guillermo pidió replicar el recorrido del archivo local `Screenshare - 2026-11-07 4_29_57 PM.mp4`, aplicando `grill-with-docs`. El archivo dura aproximadamente 3:44 y no contiene audio. Se analiza como referencia visual, sin adoptar automáticamente las reglas del portal mostrado.

Observado en el video de Inmuebles24:

- Selección de operación: Venta, Renta y Temporada. Tipo y subtipo de inmueble: se observa la selección Casa / Casa de ciudad, pero los menús no se muestran desplegados; el catálogo completo no puede deducirse del video.
- Ubicación con dirección, estado, municipio, colonia, mapa y opción exacta o aproximada, visible alrededor de 0:40.
- Características, superficies, antigüedad, precio, título y descripción.
- Multimedia con foto principal y controles de edición; también videos, planos y recorrido 360. En 2:25, el texto indica entre 5 y 50 fotos y videos de YouTube opcionales. Estos límites pertenecen a la referencia, no son acuerdos de Maia.
- Selección de comodidades y datos adicionales.
- Planes de publicación y vista previa con datos de contacto públicos, visible alrededor de 3:40. El recorrido llega a un botón «Publicar»; no acredita una publicación completada.
- Opciones visibles para guardar y salir. El video no demuestra cómo se recupera un borrador ni los permisos de acceso.

Catálogo visible extraído para Q9:

- Ubicación: calle y número, estado, ciudad o municipio, colonia, subdivisión, ubicación exacta o aproximada y mapa.
- Datos del inmueble: recámaras, baños, medios baños, estacionamientos, superficie construida y total, antigüedad (a estrenar, años de antigüedad o en construcción), precio, moneda, mantenimiento o sin mantenimiento, título y descripción.
- Características generales: acceso para personas con una condición cuyo texto aparece truncado, alberca, amueblado, caseta de guardia, chimenea, cocina integral, cuarto de servicio, escuelas cercanas, frente a parque, jacuzzi y permite mascotas.
- Servicios: aire acondicionado, área de juegos infantiles, calefacción, gimnasio y seguridad privada.
- Exteriores: asador, cancha de squash, cancha de tenis y jardín privado.
- Ambientes: cuarto de TV y estudio.
- Adicionales: estado de conservación, bodega, elevador y niveles construidos.

El video no despliega los catálogos de tipos, subtipos, monedas y estado de conservación. Las capturas posteriores resuelven tipos, subtipos y las seis opciones de conservación. Q24 resuelve las monedas como MXN y USD. Las etiquetas truncadas no se completan por suposición. Los campos y comodidades observados forman parte del alcance solicitado; las validaciones literales del portal, como longitud de descripción o resolución de fotos, no se adoptan automáticamente.

Árbol de decisiones actualizado:

- Resuelto: sin cobro por subir la propiedad y sin planes de publicación; exclusividad en todas las operaciones admitidas.
- Se conserva el acuerdo previo: revisión humana antes de incorporación y publicación; contacto del propietario privado.
- Primera ronda resuelta: exclusividad después de revisión y antes de publicación, venta y renta, propietarios y representantes autorizados, archivos para fotos y planos y enlaces para videos y recorridos 360.
- Segunda ronda resuelta según el registro anterior. La tercera ronda aporta el catálogo en capturas, descarta Temporada, exige cuenta con email y teléfono, fija seis meses para el contrato dummy y amplía la cobertura con aprobación del equipo. La siguiente frontera se detalla abajo.

### Cierre de la entrevista funcional

Q1–Q27 resueltas según las rondas anteriores. No quedan preguntas funcionales abiertas en esta entrevista. Guillermo confirmó el recorrido consolidado y autorizó continuar. Si el diseño técnico detecta una decisión comercial nueva, explicitarla en lugar de asumirla.

Hechos del código comprobados para esta frontera: acceso actual solo staff por email y contraseña, sin registro de propietario, verificación de email, recuperación ni envío de correo implementados. El celular del website se confirma como bien escrito y no acredita posesión. La dirección pública actual se entrega íntegra al público y se usa en citas; el diseño debe separar la dirección privada antes de admitir datos exactos no publicables.

El entendimiento compartido quedó confirmado por Guillermo; la implementación está autorizada. Las pantallas y reglas del portal del video son referencia visual, no instrucciones para Maia.

### Diseño técnico pendiente

1. Conversión de imágenes comunes de celular y navegador, almacenamiento, variantes web, límites de recursos y recuperación de cargas fallidas.
2. Registro, verificación por email y recuperación de contraseña; autorización por cuenta para borradores, archivos, solicitudes y aceptación del dummy.
3. Persistencia de revisión, solicitudes de cambio y retirada, aceptación versionada, renovaciones y mantenimiento del vencimiento.
4. Ampliación compatible de inventario, esquemas, herramientas, búsqueda y presentación para categorías, monedas y ubicaciones nacionales. Nunca comparar importes de distintas monedas como equivalentes ni aplicar una conversión implícita.
5. Ubicación exacta privada, proyección aproximada pública y mapa; evitar divulgar coordenadas privadas desde APIs, agente o metadatos de imágenes.
6. Migraciones, pruebas de los recorridos y compilación, preservando inventario preexistente, contratos HTTP compatibles y datos.

## Implementación prevista

Respetar [la estructura del proyecto](../architecture/code-structure.md): pantalla en `main-website`, entrada en `app`, revisión en `crm`, transporte en `api` y validaciones, persistencia e incorporación en `datalayer`.

Reutilizar el inventario y la publicación existentes. Mantener las solicitudes fuera del inventario público hasta la revisión. Las fotos necesitan definir almacenamiento y validación de archivos antes de implementar su carga; el inventario actual guarda referencias a imágenes.

## Criterios de aceptación

- Enviar una propiedad de venta y otra de renta, con precio y datos de contacto.
- Mostrar ambas en CRM y ninguna en búsqueda o fichas públicas antes de revisión y publicación.
- Conservar datos y opinión solicitada sin divulgar contacto ni notas internas.
- Incorporar cada solicitud una sola vez aunque haya doble clic o reintento.
- Publicar una propiedad revisada mediante el flujo existente y encontrarla desde website y agente.
- Descartar una solicitud sin crear una propiedad pública.
- Proteger operaciones del CRM con autenticación y CSRF, y validar entradas y archivos en backend.
- Comprobar formulario y revisión en móvil y escritorio.
- Cargar imágenes grandes sin exigir compresión manual, comprobar reducción automática, orientación y calidad visible en la galería. Verificar reintento de una carga fallida sin perder las demás fotos.
- Comprobar el mínimo de cinco fotos al completar multimedia y enviar, conservando borradores incompletos. Planos y recorrido 360 no bloquean el envío por estar ausentes.
- Exigir cuenta con email y teléfono para el recorrido de publicación, sin conceder al propietario permisos del CRM.
- Admitir ubicación fuera de la zona base y comprobar que solo una propiedad aprobada por el equipo aparece en el inventario público.
- Probar el contrato dummy de seis meses sin tratar el guardado del borrador como aceptación.

## Pendientes conservados del incremento 4

- [ ] Comprobar aprobación de las plantillas en Meta. El último estado registrado es PENDING, sin nueva consulta en esta revisión.
- [ ] Sincronizar estados y verificar variables en CRM; activar las plantillas aprobadas que correspondan.
- [ ] Acordar destinatario y texto para una entrega controlada; comprobar entrega, respuesta y registro en CRM.
- [ ] Completar la validación del seguimiento real con permiso vigente, conservando bajas y sin duplicar envíos.

Guillermo confirmó que las pruebas realizadas funcionan. Esta nota no marca como ejecutadas todas las casillas históricas ni acredita una entrega con plantillas todavía pendientes. La [lista del cuarto incremento](../testing/cuarto-incremento.md) conserva la evidencia.
