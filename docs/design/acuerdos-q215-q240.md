# Acuerdos de diseño: Q215–Q240

Consolidación: 24 de octubre de 2026. Fuente de decisiones: conversación con Guillermo. Etapa actual: **5, tecnologías y diseño**. No autoriza comenzar implementación ni contratar servicios.

Este documento recoge los acuerdos recientes y sus correcciones. No sustituye todas las decisiones anteriores del proyecto ni declara completo el diseño técnico. Las recomendaciones de los informes de investigación solo son decisiones cuando Guillermo las acepta en la conversación.

## 1. Conversación y notas de voz

**Q215, reformulada:** Haiku permanece como modelo conversacional. La primera versión atiende mensajes escritos; las notas de voz quedan pospuestas. No hay proveedor de transcripción elegido.

**Q216–Q217:** para una incorporación posterior de voz, se aceptaron límites iniciales de cinco minutos y 10 MB por nota y monitoreo del procesamiento. No se implementan ahora. La política previamente acordada conserva la transcripción y elimina el audio temporal.

**Q218:** agrupar mensajes consecutivos con una espera inicial configurable de tres segundos desde el último mensaje, con máximo de diez segundos desde el primero.

**Q219:** incorporar las correcciones antes de responder o ejecutar una acción pendiente. Si una acción externa ya ocurrió, conservar el resultado y resolver el siguiente paso sin repetirla.

**Q220:** un único aviso de espera después de 15 segundos desde el primer mensaje pendiente, únicamente si el trabajo sigue en curso. No repetir avisos ni prometer una duración.

**Q221:** presupuesto inicial configurable de 60 segundos por trabajo, incluyendo agrupación, modelo, herramientas y reintentos. Al agotarlo, no iniciar nuevas acciones; registrar el estado y responder de acuerdo con lo que realmente ocurrió. Verificar operaciones externas con resultado desconocido antes de repetirlas.

**Q222:** un solo procesamiento activo por conversación. Los mensajes nuevos quedan pendientes para la siguiente revisión. Comprobar vigencia de la respuesta frente a la información más reciente antes de enviarla.

Los tiempos son valores de diseño aprobados, no mediciones de rendimiento. Falta detallar su implementación y comprobar su comportamiento bajo carga y mensajes continuos.

## 2. CRM, fallos y control humano

Guillermo corrigió el enfoque inicial de **Q223–Q224**: el CRM debe mostrar pocas etapas comerciales. Las llamadas al modelo, sus reintentos y sus tiempos no se convierten en estados comerciales.

- CRM: etapa comercial, asesor responsable, siguiente acción y resultado.
- Diagnóstico técnico: logs de ejecución que permitan relacionar trabajos, mensajes y errores.
- Si un error impide atender a un prospecto, crear atención pendiente con responsable y contexto; no cambiar su etapa comercial por el fallo.
- Si el sistema resuelve la atención antes de que el asesor tome la tarea, cerrarla automáticamente dejando registro.
- Si el asesor ya tomó la tarea, mantener el control humano hasta que él lo libere desde el CRM.

No se aprobó una herramienta específica de trazas ni duplicar conversaciones completas en otra plataforma de observabilidad. Las propuestas originales de detalle técnico en CRM quedaron corregidas.

**Q225, corregida:** no incorporar monitor externo de disponibilidad durante Beta. Guillermo revisará fallos mediante logs. El diseño no exige un panel propio ni alertas externas para esa fase.

## 3. Pruebas bajo control del desarrollador

**Q226, corregida:** una sola base de datos. Guillermo identifica los registros de prueba mediante nombres que él controla. No imponer bases ni ambientes separados para desarrollo y piloto.

**Q227, corregida:** Guillermo controla la distinción entre pruebas y acciones reales. No imponer un modo de simulación ni una separación automática de WhatsApp, Telegram o Google Calendar.

Estas decisiones no eliminan las comprobaciones de cada recorrido; dejan la ejecución de las pruebas bajo control manual del desarrollador.

## 4. Orden de construcción

| Incremento | Recorrido acordado | Referencia |
|---|---|---|
| 1 | Carga manual de propiedades en CRM → búsqueda conversacional en website → consulta del inventario mediante herramienta del backend → propiedades reales → conversación y resultado registrados. | Q228 |
| 2 | Interés en una propiedad → celular e identidad verificada con mecanismo acordado → interés y conversación en CRM → asesor según propiedad → notificación por Telegram. El prospecto puede seguir en website o elegir WhatsApp. | Q229 |
| 3 | Solicitud de visita → ventanas de la propiedad y disponibilidad de Google Calendar → opciones → confirmación → calendario, CRM y notificación. Incluye reprogramación, cancelación y recuperación ante errores. | Q230 |
| 4 | Ciclo de seguimiento de 28 días, únicamente en días acordados. Antes de enviar, comprobar pertinencia según conversación, etapa comercial, control humano y autorización de contacto. | Q230 |
| 5 | Acompañamiento posterior a intención de compra o renta, activado por el asesor en CRM. Próximos pasos, recordatorios e información aprobada; avances registrados por el asesor. Santiago valida previamente los procesos de venta y renta. Checklist inicial, sin almacenar documentos del comprador. | Q231 |
| 6 | Formulario manual del propietario con precio solicitado → revisión desde CRM → incorporación al inventario. Opinión de valor con revisión humana, según Q240. | Q231, Q240 |

Los logs y las comprobaciones de los recorridos se incorporan desde el primer incremento. El orden no es un calendario ni una autorización para comenzar código.

## 5. Criterios de fases

### Alpha, Q232

Local mediante túnel, con pruebas internas de Guillermo y Santiago. Completar los tres primeros incrementos y comprobar:

- Resultados que respetan requisitos de búsqueda.
- Interés registrado y entregado a un asesor responsable.
- Cita confirmada reflejada en Google Calendar y CRM.
- Solicitud de atención humana con contexto y control transferido al asesor.
- Fallos registrados sin presentarlos como operaciones exitosas.

Seguimiento, acompañamiento y captación pueden seguir incompletos durante Alpha.

### Beta, Q233

Local mediante túnel, con pocos asesores y pocas propiedades reales. Guillermo y Santiago validan el ciclo de prospección: búsqueda, interés con responsable, citas, atención humana y seguimiento pertinente sin duplicados.

Las fechas de seguimiento pueden comprobarse mediante pruebas controladas sin esperar 28 días naturales. Durante Beta se continúa completando y ajustando acompañamiento y captación. La inspección técnica se realiza mediante logs.

### Release Candidate, Q234–Q238

Despliegue en AWS, presupuesto contenido y validación antes de GA. Diseño inicial: una máquina para aplicación, workers y PostgreSQL propio, con copias fuera de la máquina y restauración comprobada.

Se comparó esa topología con aplicación + RDS PostgreSQL. Lightsail es una referencia de cálculo, no una elección definitiva de producto, región o tamaño. Contrastar mediciones de Beta y coste de RDS antes de contratar.

Actualizaciones manuales con pausa breve aceptada:

1. Preparar la versión antes de detener la actual.
2. Dejar terminar trabajos activos dentro de un límite.
3. Aplicar migraciones y arrancar.
4. Comprobar búsqueda, CRM y procesamiento de mensajes.

Mantener trabajos pendientes en PostgreSQL y verificar operaciones externas de resultado desconocido antes de repetirlas. El límite de drenaje y la duración de la pausa siguen sin cuantificar.

Conservar la versión anterior y procurar compatibilidad de las migraciones. Revisar cada cambio de esquema; no todas las migraciones permiten volver al código anterior. Restaurar una copia de PostgreSQL puede perder cambios posteriores, por lo que no es un rollback automático de aplicación.

Migrar datos de Beta preservando prospectos, conversaciones, responsables, etapas, próximas acciones, citas y referencias externas, seguimiento y trabajos pendientes. No reiniciar ciclos de 28 días ni recrear citas por migrar. Corte manual con un solo entorno procesando conversaciones; revisar pertinencia de pendientes antes de reanudarlos.

### General Availability, Q239

Para una sola inmobiliaria. Validar en AWS búsqueda, interés, asignación, atención humana, citas, seguimiento, acompañamiento y captación manual.

- Sin errores conocidos que pierdan información, dupliquen acciones o dejen prospectos sin atención.
- Actualización y recuperación de despliegues comprobadas.
- Restauración de datos comprobada.
- Coste y consumo observados compatibles con la operación.

GA no exige incorporar otras inmobiliarias ni cambiar automáticamente la infraestructura.

## 6. Opinión de valor inicial, Q240

No incluir valoración automática en la primera versión estable. El propietario captura su precio y puede marcar **«Solicitar una opinión de valor»**. La solicitud llega al CRM; Santiago o el asesor designado revisa, registra y comunica su opinión.

Una valoración automática requiere diseñar posteriormente fuentes de comparables, método y revisión. No condiciona GA.

Actualización del 20 de noviembre de 2026: Guillermo pidió diseñar el [registro de cierres e historial para comparables](cierres-y-comparables.md), para acumular datos de operaciones reales y características similares. Este frente no cambia la definición de opinión de valor manual ni aprueba una valoración automática. El alcance y las reglas se resolverán mediante entrevista antes de implementar.

## 7. Pendientes explícitos

- Herramienta de observabilidad avanzada, si una necesidad concreta la justifica. No es un requisito añadido para Beta.
- Producto AWS definitivo, región, capacidad y presupuesto aprobados; revisar consumo medido y precios vigentes antes de contratar.
- Detalles de publicación HTTPS, despliegue, migración y recuperación; límite de drenaje y ensayos de restauración.
- Validación de los pasos de acompañamiento de compra y renta con Santiago.
- Especificaciones técnicas necesarias para construir los incrementos; esta consolidación no demuestra que todas estén cerradas.
- Transcripción de voz y valoración automática, pospuestas.

Investigaciones relacionadas: [AWS para RC](../research/aws-rc-2026-10-24.md) y [transcripción de voz](../research/transcripcion-voz-2026-10-23.md). Sus comparaciones permanecen como evidencia y propuestas; prevalecen los acuerdos corregidos en este documento.
