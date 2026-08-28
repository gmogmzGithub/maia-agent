# Revisión de negocio inmobiliario con Santiago

## Propósito

Este es el documento único para recopilar las decisiones, datos y validaciones que
requieren la experiencia profesional de Santiago en ventas y operación de bienes
raíces. No es un cuestionario técnico ni una solicitud para que Santiago diseñe
software.

La intención es evitar dos errores:

1. construir reglas inmobiliarias a partir de suposiciones de ingeniería;
2. pedirle a Santiago que decida detalles de seguridad, infraestructura o
   programación que no pertenecen a su especialidad.

## Cómo responder

Para cada punto, Santiago puede escribir una de estas respuestas:

- `VALIDO`: la recomendación representa correctamente la operación;
- `CAMBIAR`: explicar qué debe cambiar y por qué;
- `PROBAR`: no existe certeza suficiente y debe medirse en el piloto;
- `NO APLICA`: indicar la razón;
- `REQUIERE TERCERO`: identificar a la asociación, colaborador, contador, abogado
  o proveedor que debe responder.

Cada respuesta debe incluir, cuando sea posible, un ejemplo real pero anónimo.
No se deben pegar nombres, teléfonos, conversaciones, contratos ni documentos de
clientes en este archivo público.

## Prioridades

- **P0 — Bloquea piloto**: debe resolverse antes de atender clientes reales.
- **P1 — Define operación**: debe resolverse antes de automatizar ese flujo.
- **P2 — Optimiza negocio**: puede probarse con datos después de iniciar.
- **P3 — Futuro**: no condiciona el MVP.

## Resumen de asuntos que bloquean el piloto

| ID | Prioridad | Santiago debe confirmar o proporcionar | Estado |
|---|---|---|---|
| SAN-001 | P0 | Qué inventario propio puede publicar Larevia y con qué autorización documental | Pendiente |
| SAN-002 | P0 | Qué acceso real tiene su cuenta de EasyBroker, incluido API MLS | Pendiente |
| SAN-003 | P0 | Qué propiedades de colaboradores puede consultar, compartir y publicar | Pendiente |
| SAN-004 | P0 | Campos mínimos y fuente confiable de precio, disponibilidad y comisión | Pendiente |
| SAN-005 | P0 | Horarios reales de atención, calendario y capacidad para realizar visitas | Pendiente |
| SAN-006 | P0 | Etapas, motivos de pérdida y datos que el asesor debe registrar después de una visita | Pendiente |
| SAN-007 | P0 | Condiciones bajo las cuales una propiedad puede mostrar u ocultar dirección y precio | Pendiente |
| SAN-008 | P0 | Quién puede autorizar fotografías y material público de cada propiedad | Pendiente |
| SAN-009 | P0 | Lenguaje comercial correcto para no prometer compra, venta, disponibilidad o comisión | Pendiente |
| SAN-010 | P0 | Qué consentimientos obtiene hoy de un prospecto y mediante qué formularios o canales | Pendiente |
| SAN-011 | P0 | Qué propiedades y prospectos anónimos participarán en el primer piloto | Pendiente |
| SAN-012 | P0 | Qué resultado y qué señal de daño detendrán o ampliarán el piloto | Pendiente |

## 1. Marca, mercado y propuesta de servicio

### SAN-013 — Promesa central de Larevia

**Prioridad:** P1  
**Recomendación actual:** `Acompañamiento inmobiliario que sí continúa`.  
**Santiago debe opinar:** si expresa una diferencia real frente a otras
inmobiliarias, qué evidencia operativa la respalda y qué podría interpretar de
manera incorrecta un cliente.

**Respuesta:** Pendiente.

### SAN-014 — Identidad del equipo

**Prioridad:** P1  
**Recomendación actual:** presentar al equipo como `Especialistas inmobiliarios` y
al experto asignado como `Tu especialista en esta propiedad`.  
**Santiago debe opinar:** si esos términos son naturales, creíbles y profesionalmente
correctos en Guadalajara.

**Respuesta:** Pendiente.

### SAN-015 — Zona inicial de servicio

**Prioridad:** P0  
**Recomendación actual:** Guadalajara, Zapopan y Tlaquepaque; no prometer operación
fuera de esa zona durante el MVP.  
**Santiago debe proporcionar:** colonias realmente atendibles, zonas que deban
excluirse temporalmente y tiempos de traslado que afecten la agenda.

**Respuesta:** Pendiente.

### SAN-016 — Tipos de operación

**Prioridad:** P1  
**Santiago debe confirmar:** qué prioridad tendrán venta, renta, preventa,
desarrollos, terrenos, locales, bodegas y captación de propiedades; cuáles pueden
esperar una versión posterior.

**Respuesta:** Pendiente.

### SAN-017 — Qué significa servicio premium

**Prioridad:** P1  
**Recomendación actual:** la calidad de atención es excelente para todas las
propiedades; Premium y Super Premium cambian presentación, no dignidad ni prioridad
humana.  
**Santiago debe opinar:** qué esperan realmente los compradores y propietarios de
alto valor sin introducir promesas inviables.

**Respuesta:** Pendiente.

## 2. Calificación del prospecto y objetivo de Maia

### SAN-018 — Calificación mínima útil

**Prioridad:** P0  
**Recomendación actual:** conocer operación, zona aceptable, rango económico,
horizonte aproximado, requisitos indispensables y un medio legítimo de contacto.  
**Santiago debe indicar:** qué datos cambian realmente su decisión de atender,
buscar una propiedad o agendar una visita.

**Respuesta:** Pendiente.

### SAN-019 — Preguntas que generan abandono

**Prioridad:** P1  
**Santiago debe identificar:** preguntas que los prospectos consideran invasivas,
prematuras o innecesarias y cómo las formula él de manera natural.

**Respuesta:** Pendiente.

### SAN-020 — Señales de alta intención

**Prioridad:** P1  
**Santiago debe definir:** conductas o respuestas que en su experiencia justifican
prioridad humana, sin usar edad, apariencia, nacionalidad u otras inferencias
discriminatorias.

**Respuesta:** Pendiente.

### SAN-021 — Límite comercial de Maia

**Prioridad:** P0  
**Recomendación actual:** Maia atiende al prospecto, entiende su necesidad,
responde con información autorizada, propone opciones y concreta una cita. Después
de la cita no negocia, asesora legalmente, recibe documentos ni lleva el cierre.  
**Santiago debe validar:** si alguna tarea previa a la cita falta o si alguna tarea
incluida debe pertenecer siempre al asesor.

**Respuesta:** Pendiente.

### SAN-022 — Captación de propiedades

**Prioridad:** P1  
**Recomendación actual:** Maia recibe datos básicos de alguien que desea vender o
rentar y entrega el caso a Santiago; no valúa, promete comisión, acepta documentos
ni publica automáticamente.  
**Santiago debe indicar:** datos mínimos para decidir si desea contactar al
propietario.

**Respuesta:** Pendiente.

### SAN-023 — Solicitud de atención humana

**Prioridad:** P1  
**Recomendación actual:** Maia avisa de inmediato y dice que hará lo posible para
que el asesor contacte en los próximos minutos sin prometer disponibilidad.  
**Santiago debe validar:** frase, expectativa y canal de alerta operativo.

**Respuesta:** Pendiente.

## 3. Seguimiento y reactivación

### SAN-024 — Significado del proceso original de 28 días

**Prioridad:** P1  
**Santiago debe explicar:** qué significan `SI (2)`, `DÍA 22 (2 A)`, `soft
appointment +72 horas`, `solid appointment -72 horas` y `llamada de segundo
filtro`. La explicación servirá como conocimiento operativo aunque el producto no
adopte literalmente esa nomenclatura.

**Respuesta:** Pendiente.

### SAN-025 — Cadencia conservadora inicial

**Prioridad:** P0  
**Recomendación actual:** respuesta inmediata y, cuando exista permiso, intentos en
días 1, 3, 7, 14 y 28; cualquier respuesta detiene la secuencia genérica.  
**Santiago debe opinar:** qué contenido de valor tendría cada contacto, qué intento
debe ser humano y qué horarios son respetuosos para su mercado.

**Respuesta:** Pendiente.

### SAN-026 — Llamadas

**Prioridad:** P0  
**Recomendación actual:** las llamadas son tareas humanas registradas, no llamadas
automáticas.  
**Santiago debe definir:** cuándo una llamada aporta valor, quién la realiza, cuántos
intentos son razonables y qué se registra cuando no contestan.

**Respuesta:** Pendiente.

### SAN-027 — Momento de dormancia

**Prioridad:** P1  
**Recomendación actual:** silencio al final del ciclo produce `Dormida`, no
`Perdida`.  
**Santiago debe confirmar:** cuándo una oportunidad debe continuar activa, quedar
dormida o declararse perdida, y cuáles son los motivos comerciales válidos.

**Respuesta:** Pendiente.

### SAN-028 — Reactivación por nueva propiedad

**Prioridad:** P1  
**Recomendación actual:** sólo una coincidencia explicable, disponible y revisada
por administración puede iniciar una nueva conversación, con consentimiento y sin
tratar una necesidad de más de 90 días como vigente.  
**Santiago debe definir:** qué coincidencias justifican contactar de nuevo y qué
diferencias son aceptables en precio, zona y características.

**Respuesta:** Pendiente.

### SAN-029 — Campañas de desarrollos

**Prioridad:** P1  
**Santiago debe explicar:** cómo segmenta hoy compradores para un desarrollo, qué
datos necesita de cada modelo, qué argumentos son verificables y quién debe revisar
la audiencia antes del envío.

**Respuesta:** Pendiente.

### SAN-030 — Indicadores de daño

**Prioridad:** P1  
**Santiago debe acordar:** qué cantidad de quejas, solicitudes de baja, bloqueos,
errores de propiedad o contactos inoportunos debe detener una campaña o cadencia.

**Respuesta:** Pendiente.

## 4. Citas, agenda y trabajo de asesores

### SAN-031 — Duración de visita

**Prioridad:** P0  
**Recomendación actual:** 90 minutos por visita durante el MVP.  
**Santiago debe validar:** si funciona para casas, departamentos, terrenos y
desarrollos, y qué casos siempre requieren coordinación manual.

**Respuesta:** Pendiente.

### SAN-032 — Disponibilidad real

**Prioridad:** P0  
**Santiago debe proporcionar:** horarios laborales, anticipación mínima, días no
laborables, bloques personales, política de traslados y quién mantiene actualizado
Google Calendar.

**Respuesta:** Pendiente.

### SAN-033 — Experto de la propiedad

**Prioridad:** P0  
**Recomendación actual:** cada Property puede tener experto principal y suplentes;
el experto recibe primero las oportunidades específicas.  
**Santiago debe definir:** criterios para nombrarlo, cuándo puede cambiar y qué
ocurre cuando no está disponible.

**Respuesta:** Pendiente.

### SAN-034 — Asesor responsable frente a experto

**Prioridad:** P1  
**Santiago debe validar:** si el asesor que lleva al prospecto debe conservarlo
aunque otra persona sea experta en una propiedad y cómo se atribuye la visita y la
venta.

**Respuesta:** Pendiente.

### SAN-035 — Ausencias

**Prioridad:** P1  
**Recomendación actual:** sólo el administrador registra ausencias; no existe
autoasignación silenciosa de oportunidades o citas existentes.  
**Santiago debe validar:** proceso cotidiano y anticipación necesaria.

**Respuesta:** Pendiente.

### SAN-036 — Recordatorios

**Prioridad:** P1  
**Recomendación actual:** confirmación inmediata, recordatorio 24 horas antes y
otro el día de la cita.  
**Santiago debe opinar:** contenido, horarios y condiciones que evitarían mensajes
duplicados o innecesarios.

**Respuesta:** Pendiente.

### SAN-037 — Inasistencia y cancelación

**Prioridad:** P1  
**Recomendación actual:** cancelar una cita no cierra la oportunidad; una
inasistencia permite una invitación de reprogramación sólo si el asesor la
autoriza.  
**Santiago debe definir:** cómo distingue una inasistencia de un error operativo y
cuándo vale la pena buscar una nueva cita.

**Respuesta:** Pendiente.

### SAN-038 — Registro posterior a visita

**Prioridad:** P0  
**Recomendación actual:** el asesor registra si ocurrió, interés conocido, próxima
acción y resultado.  
**Santiago debe diseñar:** el formulario mínimo que realmente completaría después
de cada visita y el tiempo razonable para hacerlo.

**Respuesta:** Pendiente.

## 5. Propiedades, Listings y EasyBroker

### SAN-039 — Inventario propio

**Prioridad:** P0  
**Santiago debe entregar fuera del repositorio:** lista inicial de propiedades,
fuente de sus datos, permiso de publicación, responsable, precio, disponibilidad y
material visual autorizado.

**Respuesta:** Pendiente.

### SAN-040 — Acceso EasyBroker

**Prioridad:** P0  
**Santiago debe confirmar directamente en su cuenta o con EasyBroker:** plan
contratado, acceso API, acceso API MLS, alcance de colaboradores y restricciones.
Pertenecer a una asociación no se tratará como prueba suficiente.

**Respuesta:** Pendiente.

### SAN-041 — Autoridad de publicación externa

**Prioridad:** P0  
**Santiago debe explicar:** cuándo puede compartir una propiedad de colaborador por
WhatsApp, cuándo puede publicarla en Larevia y qué atribución o autorización se
requiere para texto y fotografías.

**Respuesta:** Pendiente.

### SAN-042 — Comisión compartida

**Prioridad:** P0  
**Santiago debe identificar:** dónde aparece la comisión vigente, quién la confirma,
cuándo puede cambiar y qué evidencia debe conservarse antes de recomendar o agendar.

**Respuesta:** Pendiente.

### SAN-043 — Frescura de datos externos

**Prioridad:** P0  
**Santiago debe definir:** cuánto tiempo considera confiables disponibilidad,
precio, comisión y condiciones antes de exigir una nueva verificación.

**Respuesta:** Pendiente.

### SAN-044 — Contacto con colaborador

**Prioridad:** P1  
**Santiago debe describir:** proceso para confirmar disponibilidad, obtener permiso,
coordinar una visita y registrar la respuesta de otro agente.

**Respuesta:** Pendiente.

### SAN-045 — Duplicados físicos

**Prioridad:** P1  
**Recomendación actual:** sólo fusionar visualmente Listings cuando exista evidencia
de que representan la misma propiedad; priorizar la Listing propia.  
**Santiago debe indicar:** qué evidencia utiliza profesionalmente para confirmar
identidad y cómo manejar diferencias de precio o descripción.

**Respuesta:** Pendiente.

### SAN-046 — Campos por tipo de propiedad

**Prioridad:** P0  
**Santiago debe definir los campos indispensables y opcionales para:** casa,
departamento, terreno, local, bodega y unidad de desarrollo. No se mostrarán
recámaras o baños en tipos donde no correspondan.

**Respuesta:** Pendiente.

### SAN-047 — Mantenimiento y costos adicionales

**Prioridad:** P0  
**Santiago debe indicar:** cómo se expresan mantenimiento, depósitos, cuotas,
equipamiento, impuestos u otros costos sin confundirlos con el precio principal y
qué ocurre cuando se desconocen.

**Respuesta:** Pendiente.

### SAN-048 — Precio oculto

**Prioridad:** P1  
**Recomendación actual:** el administrador lo oculta manualmente; el sitio muestra
`Precio disponible previa consulta` y Maia puede comunicar el precio autorizado en
privado.  
**Santiago debe validar:** cuándo se usa profesionalmente y si existe algún caso en
que tampoco deba comunicarse por conversación.

**Respuesta:** Pendiente.

### SAN-049 — Venta y renta simultáneas

**Prioridad:** P1  
**Recomendación actual:** una Listing puede contener ambas ofertas con precios y
disponibilidades separadas.  
**Santiago debe validar:** qué ocurre operacionalmente cuando se renta, vende,
reserva o cambia una de las ofertas.

**Respuesta:** Pendiente.

### SAN-050 — Desarrollos y modelos

**Prioridad:** P1  
**Santiago debe describir:** relación real entre desarrollo, etapa, torre,
prototipo/modelo, unidad disponible, precio desde, inventario, entrega y promoción;
qué puede publicarse cuando aún no existe una unidad individual.

**Respuesta:** Pendiente.

## 6. Sitio, búsqueda y presentación de propiedades

### SAN-051 — Selección de portada

**Prioridad:** P1  
**Recomendación actual:** seis a ocho propiedades elegidas editorialmente.  
**Santiago debe definir:** qué mezcla demuestra mejor el negocio sin convertir la
portada en una lista de inventario viejo.

**Respuesta:** Pendiente.

### SAN-052 — Filtros que sí usan los clientes

**Prioridad:** P1  
**Santiago debe ordenar:** operación, municipio/colonia, tipo, precio, recámaras,
baños, superficie, estacionamientos, amueblado y amenidades según su utilidad real.

**Respuesta:** Pendiente.

### SAN-053 — Nombres de zonas y colonias

**Prioridad:** P0  
**Santiago debe aportar:** vocabulario local, equivalencias, errores frecuentes y
agrupaciones comerciales que los clientes usan para Guadalajara, Zapopan y
Tlaquepaque.

**Respuesta:** Pendiente.

### SAN-054 — Alternativas aproximadas

**Prioridad:** P1  
**Santiago debe definir:** qué desviaciones de zona, precio, superficie, recámaras
o amenidades son razonables para mostrar como alternativa, y cuáles cambian por
completo la necesidad.

**Respuesta:** Pendiente.

### SAN-055 — Ubicación pública

**Prioridad:** P0  
**Recomendación actual:** mostrar sólo Public Location y reservar la dirección de
visita para el flujo autorizado.  
**Santiago debe indicar:** nivel apropiado por tipo de propiedad y riesgos de
mostrar calle, fraccionamiento, torre o coordenadas aproximadas.

**Respuesta:** Pendiente.

### SAN-056 — Orden y grupos fotográficos

**Prioridad:** P1  
**Santiago debe validar:** portada y secuencia recomendada para fachada, áreas
sociales, cocina, recámaras, baños, exteriores y amenidades; identificar diferencias
por tipo de propiedad.

**Respuesta:** Pendiente.

### SAN-057 — Requisitos por nivel visual

**Prioridad:** P1  
**Recomendación actual:** 6 fotografías para Larevia, 12 y cuatro grupos para
Premium, 20 y seis grupos para Super Premium, con requisitos adicionales de
resolución.  
**Santiago debe validar:** si esos mínimos son comercialmente alcanzables y qué
material falta para desarrollos o terrenos.

**Respuesta:** Pendiente.

### SAN-058 — Rangos de venta y renta

**Prioridad:** P1  
**Recomendación actual:** Larevia debajo de MXN 12 millones, Premium entre MXN 12 y
20 millones, Super Premium arriba de MXN 20 millones; renta Larevia debajo de MXN
50 mil, Premium entre MXN 50 y 85 mil y Super Premium arriba de MXN 85 mil; todas
las ofertas en USD son Premium como mínimo.  
**Santiago debe validar:** si estos rangos representan el mercado metropolitano y
con qué frecuencia deben revisarse.

**Respuesta:** Pendiente.

## 7. Patrocinio de propiedades

### SAN-059 — Quién compraría

**Prioridad:** P1  
**Recomendación actual:** propietarios, desarrolladores y colaboradores con Listing
elegible.  
**Santiago debe identificar:** compradores reales probables, objeciones y quién
toma la decisión de pago.

**Respuesta:** Pendiente.

### SAN-060 — Diferencia entre destacada y patrocinada

**Prioridad:** P1  
**Recomendación actual:** `Destacada` es selección editorial sin pago;
`Patrocinada` es visibilidad comprada y claramente etiquetada.  
**Santiago debe validar:** si el lenguaje se entiende y evita conflictos con
propietarios y colaboradores.

**Respuesta:** Pendiente.

### SAN-061 — Paquete inicial

**Prioridad:** P1  
**Recomendación actual:** 30 días en búsqueda, portada o ambas, sin subasta, costo
por clic ni renovación automática.  
**Santiago debe opinar:** si el periodo y las superficies son fáciles de vender y
qué expectativa intentará negociar un comprador.

**Respuesta:** Pendiente.

### SAN-062 — Precio fundador

**Prioridad:** P2  
**Recomendación actual:** no inventar precio antes de instrumentar tráfico y hacer
pilotos.  
**Santiago debe proponer:** clientes piloto, precio introductorio defendible y
condiciones que permitan aprender sin regalar indefinidamente el servicio.

**Respuesta:** Pendiente.

### SAN-063 — Cotización

**Prioridad:** P1  
**Santiago debe validar:** vista previa, superficies, fechas, precio, estimación de
exposición, comparables, embudo, vigencia de siete días y ausencia de resultados
garantizados. Debe indicar qué información necesita para cerrar la venta.

**Respuesta:** Pendiente.

### SAN-064 — Capacidad y exclusividad

**Prioridad:** P1  
**Recomendación actual:** una patrocinada por cada seis resultados, máximo dos en
portada y rotación equitativa; no vender capacidad que diluya excesivamente la
entrega.  
**Santiago debe opinar:** si los compradores pedirán exclusividad por zona, tipo o
periodo y si debemos rechazarla inicialmente.

**Respuesta:** Pendiente.

### SAN-065 — Requisitos comerciales de elegibilidad

**Prioridad:** P0  
**Santiago debe confirmar:** qué defectos de ficha, precio, disponibilidad,
fotografía, autorización o relación con el propietario impiden aceptar dinero para
promoción.

**Respuesta:** Pendiente.

### SAN-066 — Reporte que convence

**Prioridad:** P1  
**Recomendación actual:** impresiones visibles, visitas, conversaciones y citas
verificadas como cifras principales; después embudo, tendencia, interés y días
restantes.  
**Santiago debe indicar:** qué preguntas haría un propietario o desarrollador y qué
comparaciones considera creíbles.

**Respuesta:** Pendiente.

### SAN-067 — Resultado y renovación

**Prioridad:** P1  
**Santiago debe definir:** cuándo recomendaría renovar, qué desempeño considera
satisfactorio y cómo explicaría una campaña con mucha exploración pero ninguna
cita.

**Respuesta:** Pendiente.

## 8. CRM, resultados y conocimiento comercial

### SAN-068 — Etapas de oportunidad

**Prioridad:** P0  
**Recomendación actual:** Nueva, En conversación, Calificada, Buscando, Visitando,
Negociando, Ganada, Perdida o Dormida.  
**Santiago debe validar:** nombres, condiciones de entrada/salida y etapas que no
aporten acción real.

**Respuesta:** Pendiente.

### SAN-069 — Próxima acción obligatoria

**Prioridad:** P0  
**Recomendación actual:** toda oportunidad calificada activa tiene asesor
responsable y próxima acción no vencida.  
**Santiago debe validar:** qué acciones utiliza realmente y qué situaciones
justifican una excepción temporal.

**Respuesta:** Pendiente.

### SAN-070 — Motivos de pérdida

**Prioridad:** P0  
**Santiago debe proponer:** lista corta y mutuamente comprensible de motivos
conocidos, separando rechazo explícito, imposibilidad financiera, cambio de zona,
compra con tercero, propiedad no disponible, falta de seguimiento y razón
desconocida.

**Respuesta:** Pendiente.

### SAN-071 — Definición de ganada

**Prioridad:** P0  
**Recomendación actual:** venta legalmente completada, contrato de renta firmado o
contrato vinculante de preventa aceptado; una visita, apartado u oferta no son
ganada.  
**Santiago debe validar:** evidencia operacional disponible para cada tipo.

**Respuesta:** Pendiente.

### SAN-072 — Comisión

**Prioridad:** P0  
**Recomendación actual:** registrar comisión bruta esperada, ganada y cobrada sin
calcular repartos, impuestos o nómina.  
**Santiago debe definir:** momento, fuente, moneda, porcentaje o importe y cambios
que deben quedar auditados.

**Respuesta:** Pendiente.

### SAN-073 — Tablero principal de Santiago

**Prioridad:** P1  
**Santiago debe ordenar por importancia:** prospectos sin asignar, próximas acciones
vencidas, solicitudes humanas sin tomar, citas próximas, resultados sin registrar,
propiedades por revalidar, campañas y patrocinios.

**Respuesta:** Pendiente.

### SAN-074 — Información que necesita un asesor

**Prioridad:** P1  
**Santiago debe identificar:** resumen mínimo para recibir una oportunidad sin leer
toda la conversación y qué información sería peligrosa, innecesaria o sesgada.

**Respuesta:** Pendiente.

### SAN-075 — Calidad del seguimiento

**Prioridad:** P1  
**Recomendación actual:** mostrar por separado cobertura de seguimiento, conversión
y completitud de resultados.  
**Santiago debe validar:** cómo usar estas métricas para administrar sin convertirlas
en incentivos para mensajes excesivos o registros falsos.

**Respuesta:** Pendiente.

## 9. Diseño del piloto

### SAN-076 — Inventario piloto

**Prioridad:** P0  
**Santiago debe seleccionar:** conjunto pequeño pero representativo de propiedades,
incluidos tipos, zonas, precios y al menos un caso de colaborador si existe permiso.

**Respuesta:** Pendiente.

### SAN-077 — Prospectos piloto

**Prioridad:** P0  
**Santiago debe definir:** fuente de los prospectos, consentimiento disponible,
horarios atendidos, volumen máximo y procedimiento humano de emergencia.

**Respuesta:** Pendiente.

### SAN-078 — Criterio para ampliar

**Prioridad:** P0  
**Santiago debe acordar:** mínimos aceptables de respuesta útil, calificación,
citas, asistencia, cobertura de seguimiento y completitud de resultados antes de
aumentar volumen.

**Respuesta:** Pendiente.

### SAN-079 — Criterio para detener

**Prioridad:** P0  
**Santiago debe acordar:** errores de información, quejas, mensajes inoportunos,
fallos de asignación, citas incorrectas o carga operativa que obligan a pausar.

**Respuesta:** Pendiente.

### SAN-080 — Revisión semanal

**Prioridad:** P1  
**Recomendación actual:** revisión semanal corta de excepciones, propiedades,
seguimientos, citas, resultados y daño; cambios de reglas quedan versionados.  
**Santiago debe definir:** participantes, duración y decisiones que pueden tomarse
en esa reunión.

**Respuesta:** Pendiente.

## 10. Temas que Santiago debe ayudar a identificar, pero no resolver solo

Estas preguntas requieren experiencia inmobiliaria para describir la práctica,
pero la conclusión final pertenece a un abogado, contador o proveedor autorizado:

| Tema | Aportación de Santiago | Validación externa necesaria |
|---|---|---|
| Autorización de publicación | Cómo obtiene hoy permiso y documentos | Abogado inmobiliario y condiciones de cada fuente |
| Aviso de privacidad y consentimientos | Cómo se capturan prospectos y qué se les dice | Abogado mexicano de privacidad |
| REPEP y llamadas comerciales | Cómo y cuándo llama actualmente | Abogado/asesor de cumplimiento |
| Publicidad de vivienda | Afirmaciones, fichas y materiales usados | Abogado con experiencia en NOM-247 y consumo |
| Comisiones compartidas | Práctica, acuerdos y evidencia | Contrato/colaborador/asociación y abogado |
| EasyBroker | Cuenta, plan y operación observada | Confirmación escrita de EasyBroker |
| Facturación del patrocinio | Precio, descuentos y proceso comercial | Contador y proveedor de facturación |
| Retención de expedientes | Necesidad operativa histórica | Abogado de privacidad y obligaciones fiscales |

## 11. Decisiones que no deben cargarse a Santiago

Santiago puede expresar necesidades o riesgos, pero ingeniería mantiene
responsabilidad sobre:

- PostgreSQL, contenedores y topología de ejecución;
- separación entre Hermes, Product y sitio público;
- autenticación, autorización y aislamiento entre organizaciones;
- cifrado, secretos, respaldos y recuperación;
- Inbox, Outbox, idempotencia y reintentos;
- URLs firmadas, cookies seguras y protección contra abuso;
- renderizado para buscadores, mapas de sitio y datos estructurados;
- esquema físico de eventos y futura migración analítica;
- pruebas automatizadas, observabilidad y despliegue;
- selección de proveedores técnicos y modelos de inteligencia artificial.

Estas decisiones deben traducir la operación validada por Santiago, no pedirle que
elija tecnologías que no necesita conocer.

## 12. Registro de sesiones con Santiago

Cada sesión debe añadir una entrada breve y pública-segura:

```text
Fecha:
Participantes:
IDs revisados:
Decisiones validadas:
Cambios solicitados:
Datos o evidencia pendientes:
Temas enviados a tercero:
Próxima revisión:
```

Cuando una respuesta se adopte, debe actualizarse también el documento de dominio
o ADR correspondiente. Este archivo conserva la cola de validación; no debe
convertirse en una segunda fuente contradictoria de reglas ya resueltas.

## Referencias internas

- [Memoria pública del producto](../PROJECT_MEMORY.md)
- [Lenguaje del dominio](../CONTEXT.md)
- [Investigación de seguimiento por WhatsApp](research/whatsapp-lead-follow-up.md)
- [Investigación de EasyBroker](research/easybroker-integration.md)
- [Sitios de referencia y descubrimiento orgánico](research/sitios-referencia-y-descubrimiento-organico.md)
- [Decisiones de arquitectura](adr/)
