# Quinto incremento: acompañamiento posterior a la intención

Fecha: 7 de noviembre de 2026.

Estado: pospuesto por Guillermo el 7 de noviembre de 2026 para priorizar el [incremento 6, captación de propiedades](sexto-incremento-captacion.md). Se conserva este borrador. Pendiente definir y validar los procesos comerciales con Santiago antes de implementar. El incremento 4 conserva sus [pendientes de plantillas y seguimiento real](../testing/cuarto-incremento.md#actualización-de-guillermo-7-de-noviembre-de-2026).

## Alcance acordado

Según Q231 de los [acuerdos de diseño](acuerdos-q215-q240.md#4-orden-de-construcción):

- El asesor activa el acompañamiento desde CRM después de la intención de compra o renta.
- La primera versión ofrece un checklist, próximos pasos, recordatorios e información aprobada.
- El asesor registra los avances comerciales.
- Santiago valida previamente los procesos de compra y renta.
- No se almacenan documentos del comprador.

Según Q268 de los [contratos de contexto y procedimientos](contratos-q241-q265.md#contexto-y-procedimientos-q266q271), los procedimientos se versionan junto con la aplicación. Santiago valida el contenido comercial y Guillermo controla su publicación.

## Decisiones por resolver

1. **Inicio:** qué hecho confirma la intención y qué registra el asesor al activar el acompañamiento.
2. **Compra y renta:** pasos de cada proceso, orden, pasos opcionales y condiciones para avanzar.
3. **Responsabilidad:** quién realiza cada paso y quién confirma su cumplimiento.
4. **Contenido:** qué puede explicar Maia y qué requiere intervención del asesor.
5. **Recordatorios:** destinatario, canal, fecha o condición y reglas para omitir o detener avisos. Definir su relación con el seguimiento de prospección existente, sin asumir que son el mismo ciclo.
6. **Finalización:** cómo registrar cierre, desistimiento, pausa o cambio de propiedad y qué ocurre con lo pendiente.

## Propuesta de trabajo, pendiente de validar

1. Recoger un caso de renta y otro de compra con Santiago.
2. Describir cada paso con nombre, responsable, condición de inicio, confirmación de avance e información que Maia puede comunicar.
3. Revisar el recorrido en CRM y la atención al cliente antes de definir modelos, API y tareas.
4. Implementar el alcance acordado y comprobar un recorrido completo por operación, incluidos pausa y finalización.

La definición del checklist y su gestión en CRM pueden avanzar mientras Meta revisa las plantillas. Los mensajes externos deberán usar los permisos y las reglas del canal existentes; no se presupone que las plantillas de prospección sirven para acompañamiento.

## Primera decisión de esta conversación

Pendiente: confirmar si ya existe un proceso de compra y renta validado por Santiago o preparar una propuesta para su revisión. No se fijan trámites, plazos ni requisitos comerciales sin esa definición.
