# Seguimiento de leads inmobiliarios por WhatsApp en México

**Estado:** investigación para conversación de producto e ingeniería  
**Fecha de revisión:** 27 de agosto de 2026  
**Alcance:** seguimiento de leads, reactivación y recordatorios de citas. No es dictamen jurídico.

## Resumen ejecutivo

La oportunidad de Maia no es ejecutar una secuencia rígida con más disciplina que otros CRMs. Es garantizar que ningún lead quede sin dueño, contexto, siguiente acción o cierre explícito, y hacerlo sin convertir el seguimiento en presión o spam.

El calendario aportado por el operador inmobiliario —días 1, 3, 5, 7, 10, 14, 18, 22, 26 y 28 mediante llamada, WhatsApp y correo— es experiencia comercial valiosa, pero debe tratarse como una **hipótesis inicial**, no como una cadencia científicamente validada. La imagen implica al menos 22 contactos en 28 días y posiblemente más por las marcas `SI (2)` y `DIA 22 (2 A)`. No se encontró evidencia académica que valide esa intensidad, esas fechas o esos horarios para leads inmobiliarios mexicanos por WhatsApp.

Conclusiones firmes:

- La primera respuesta al lead debe ser rápida y útil. La evidencia comercial disponible relaciona una menor latencia con mayor probabilidad de contacto o calificación, pero no prueba una regla universal de cinco minutos ni garantiza una venta.
- Un calendario no debe mandar mensajes por sí solo. Cada contacto necesita consentimiento vigente, finalidad, estado del lead, valor nuevo para el cliente, supresiones y un límite de presión entre canales.
- En WhatsApp Business Platform, fuera de las 24 horas desde el último mensaje del usuario sólo se puede iniciar contacto mediante una plantilla aprobada. El seguimiento comercial, la recomendación de una nueva propiedad y la reactivación de un cliente dormido son mensajes de marketing.
- Meta exige número proporcionado y opt-in, respeto inmediato al opt-out y una ruta clara de atención humana. Recomienda separar el consentimiento para llamadas y por categorías de mensajes.
- En México, la base de leads es tratamiento de datos personales: requiere finalidad y consentimiento aplicables, aviso de privacidad, proporcionalidad, seguridad y derechos ARCO. La publicidad no puede enviarse a quien se opuso o está en el registro de exclusión de PROFECO.
- La evidencia experimental sobre recordatorios de citas sí respalda probar dos recordatorios previos —por ejemplo, 72 y 24 horas antes—, pero proviene de salud, no de bienes raíces. No respalda un contacto 72 horas después de una cita fallida sin considerar el resultado de la cita.
- La optimización debe hacerse con experimentos controlados y métricas de negocio y daño: citas realizadas y ventas incrementales, pero también opt-outs, bloqueos, quejas y contactos inútiles. Aperturas o mensajes enviados no son éxito.

## Qué evidencia existe y qué no

### 1. Rapidez de primera respuesta

Un estudio observacional difundido por *Harvard Business Review*, con datos de leads web de empresas B2B y B2C estadounidenses, encontró una caída pronunciada en la probabilidad de calificar un lead cuando el primer intento se demoraba. Es evidencia útil para priorizar la latencia, pero fue coautorado con un proveedor comercial, no fue un ensayo aleatorizado, no era inmobiliario ni mexicano y midió calificación, no compraventa cerrada. Por tanto, justifica medir y reducir el `time_to_first_meaningful_response`; no justifica prometer un múltiplo de conversión ni afirmar un umbral universal de cinco minutos. [Oldroyd, McElheran y Elkington, 2011](https://hbr.org/2011/03/the-short-life-of-online-sales-leads).

La investigación revisada por pares sobre el “sales lead black hole” sí respalda el problema organizacional: con datos de 461 vendedores en cuatro empresas, el seguimiento varió con la precalificación, el seguimiento gerencial, el volumen de leads y la experiencia/desempeño del vendedor. El hallazgo importante para Maia es sistémico: capturar leads no basta; se necesita asignación, priorización, visibilidad y rendición de cuentas. El estudio no determina una cadencia óptima para mensajes. [Sabnis et al., *Journal of Marketing*, 2013](https://doi.org/10.1509/jm.10.0047).

**Inferencia para Maia:** responder de inmediato a un mensaje entrante con información pertinente, una pregunta mínima de calificación o una ruta humana tiene mayor sustento que disparar muchos intentos posteriores. “Rápido” debe definirse y medirse por segmento y horario operativo, no mediante una cifra tomada de otro sector.

### 2. Persistencia, frecuencia y fatiga

No se encontró un ensayo controlado de cadencias multicanal para leads inmobiliarios mexicanos que compare 10 días de contacto, 22–25 impactos o el patrón aportado. Tampoco hay base para afirmar “la mejor hora” para llamar o escribir. Las cifras comerciales que suelen circular mezclan contacto, calificación, cita y venta, y suelen provenir de proveedores con datos no auditables públicamente.

Meta proporciona la señal de daño más directamente aplicable a WhatsApp: los usuarios pueden bloquear o reportar a una empresa y Meta puede limitar su capacidad de mensajería cuando acumula retroalimentación negativa o baja calidad. La política prohíbe sorprender o hacer spam y exige respetar solicitudes de cese. [WhatsApp Business Messaging Policy, secciones 1 y 7](https://whatsappbusiness.com/policy/).

**Inferencia para Maia:** cada intento adicional tiene rendimiento decreciente y riesgo acumulativo. Una secuencia debe detenerse o cambiar de modo cuando el lead responde, agenda, compra, rechaza, pide pausa, deja de cumplir el perfil, se invalida el número, se pierde el consentimiento o se alcanza un presupuesto de presión. El silencio no equivale a interés ni renueva el consentimiento.

### 3. Recordatorios de cita

Existe evidencia experimental sólida, aunque de salud y no de bienes raíces:

- En un ensayo con 54,066 pacientes, dos recordatorios —tres días y un día antes— redujeron más las inasistencias que uno solo; el efecto fue mayor entre personas con alto riesgo de faltar. [Steiner et al., 2018](https://pubmed.ncbi.nlm.nih.gov/30130032/).
- Un ensayo con 161,587 personas mostró que cambiar el texto del recordatorio alteraba inasistencias y cancelaciones, y concluyó que el contenido debía probarse sistemáticamente. Algunos encuadres pueden ser manipulativos; Maia no debe adoptar culpa o presión sólo porque funcionó en otro contexto. [Berliner Senderey et al., 2020](https://doi.org/10.1371/journal.pone.0234817).
- Un ensayo de dos mensajes de WhatsApp, tres y un día antes de una consulta, no encontró mejora estadísticamente significativa en asistencia. Esto recuerda que el canal por sí solo no resuelve fricción o falta de intención. [Favaretti et al., 2024](https://doi.org/10.1186/s12889-024-19894-9).

**Inferencia para Maia:** vale la pena probar recordatorios a `T-72h` y `T-24h`, con confirmación/reprogramación/cancelación en un toque. La cita debe tener estado explícito (`tentative`, `confirmed`, `rescheduled`, `cancelled`, `completed`, `no_show`), y cualquier contacto posterior debe depender del resultado real. La expresión de la imagen `SOFT APPOINTMENTS: +72 HORAS` es ambigua y debe aclararse antes de automatizarla.

## Restricciones de WhatsApp Business Platform

Estas reglas deben ser invariantes del producto, no instrucciones dejadas al modelo:

1. **Permiso para contactar.** Meta sólo permite contactar si la persona proporcionó su número y dio opt-in para mensajes o llamadas posteriores. La empresa es responsable de que ese consentimiento y los avisos cumplan la ley local. [Política de WhatsApp, 1.3](https://whatsappbusiness.com/policy/).
2. **Opt-out inmediato y globalmente coherente.** Se debe respetar cualquier solicitud, dentro o fuera de WhatsApp, de bloquear, descontinuar o excluir comunicaciones. Meta recomienda opt-ins separados por categoría y uno separado para llamadas, instrucciones claras de baja y explicación del valor recibido. [Política de WhatsApp, “Best Practices for Opt-In”](https://whatsappbusiness.com/policy/#best-practices-for-opt-in).
3. **Ventana de servicio.** Se puede responder sin plantilla sólo durante las 24 horas posteriores al último mensaje del usuario. Fuera de esa ventana, únicamente mediante una plantilla aprobada y para su propósito designado. [Política de WhatsApp, sección 2](https://whatsappbusiness.com/policy/).
4. **Clasificación.** Nutrir leads, recomendar propiedades, anunciar un desarrollo y reactivar prospectos dormidos son usos de marketing descritos por Meta y presuponen opt-in. [WhatsApp Marketing Messages](https://whatsappbusiness.com/products/conversation-categories/marketing/).
5. **Escalamiento humano.** La automatización durante la ventana de atención debe ofrecer una ruta rápida, clara y directa hacia una persona u otro canal de soporte. [Política de WhatsApp, sección 2](https://whatsappbusiness.com/policy/).
6. **Datos y seguridad.** Meta exige avisos, permisos, política de privacidad publicada y cumplimiento legal. También limita el uso de datos obtenidos de WhatsApp a lo razonablemente necesario para apoyar la mensajería con esa persona. No se deben pedir identificadores financieros o personales completos por chat. [Política de WhatsApp, sección 3](https://whatsappbusiness.com/policy/).
7. **Riesgo de plataforma.** Bloqueos, reportes, baja calidad o mensajería masiva no autorizada pueden reducir límites o terminar el acceso. La salud del número es un activo crítico del negocio, no sólo una métrica técnica. [Política de WhatsApp, sección 7](https://whatsappbusiness.com/policy/).

Consecuencia de arquitectura: el Product backend, no Hermes, debe decidir si un envío es elegible. Debe verificar ventana, plantilla/categoría, consentimiento, supresión, frecuencia, horario permitido, estado del lead, idempotencia y autorización antes de crear el envío. Hermes puede redactar dentro de parámetros aprobados o conversar; no debe poder eludir esas reglas.

## Restricciones mexicanas relevantes

### Datos personales

La Ley Federal de Protección de Datos Personales en Posesión de los Particulares vigente fue publicada el 20 de marzo de 2025 y su texto consultado incorpora la reforma del 14 de noviembre de 2025. La autoridad definida por la ley es la Secretaría Anticorrupción y Buen Gobierno. [Texto vigente de la LFPDPPP](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf).

Para Maia y el CRM implica, como mínimo:

- El tratamiento debe cumplir licitud, finalidad, lealtad, consentimiento, calidad, proporcionalidad, información y responsabilidad (arts. 5–7).
- Una finalidad nueva requiere nuevo consentimiento; el tratamiento debe ser necesario, adecuado y relevante para las finalidades declaradas (arts. 11–12).
- El aviso de privacidad debe explicar responsable, datos, finalidades, opciones para limitar uso/divulgación, mecanismos ARCO y cambios. Cuando los datos se obtienen electrónicamente, debe mostrarse al menos el aviso simplificado y enlazar al integral (arts. 14–16).
- Deben existir medidas administrativas, técnicas y físicas contra acceso, uso, pérdida o tratamiento no autorizado, así como confidencialidad para todas las personas que intervienen (arts. 18–20).
- La persona puede acceder, rectificar, cancelar u oponerse al tratamiento; los sistemas deben permitir ejercer estos derechos sin dilación (arts. 21–29).

No es suficiente decir “guardaremos todos los datos posibles para BI”. Esa formulación contradice la disciplina de finalidad y proporcionalidad. Deben definirse campos y retención por finalidad. Para analítica de largo plazo, la opción prudente es separar datos operativos identificables de conjuntos agregados o anonimizados, probar que la anonimización evita reidentificación y no conservar chats completos indefinidamente por si algún día resultan útiles. Esto es una recomendación de diseño derivada de los principios legales, no una conclusión judicial.

También deben evitarse atributos o inferencias que permitan discriminación inmobiliaria. Meta prohíbe preferencias discriminatorias basadas, entre otras características, en nacionalidad, ciudadanía, religión, edad, sexo, orientación, identidad de género, estado familiar/marital, discapacidad y condiciones médicas o genéticas. [Política de WhatsApp, sección 4](https://whatsappbusiness.com/policy/).

### Publicidad y consumidor

La Ley Federal de Protección al Consumidor:

- permite al consumidor exigir no ser molestado ni recibir publicidad por cualquier medio y oponerse a que su información se ceda a terceros (art. 17);
- prevé un registro público de consumidores que no desean uso mercadotécnico o publicitario y prohíbe publicidad a quien se opuso o está inscrito (arts. 18 y 18 Bis);
- exige que la publicidad sea veraz, comprobable, clara y no engañosa o abusiva (art. 32).

Fuente: [texto vigente de la LFPC](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPC.pdf).

PROFECO explica que el REPEP cubre números fijos y móviles frente a llamadas y mensajes de texto publicitarios. Su información operativa contempla como excepción el consentimiento expreso otorgado a un proveedor determinado; por eso el CRM debe conservar evidencia del consentimiento y no asumir que una consulta previa equivale a autorización indefinida. [PROFECO, información general del REPEP](https://repep.profeco.gob.mx/infogeneral.jsp).

La NOM-247-SE-2021 regula información comercial y publicidad de inmuebles destinados a casa habitación, y alcanza a quienes intervienen en asesoría y venta al público. Por ello, una recomendación automática no debe inventar disponibilidad, precio, ubicación, amenidades, relación de representación ni condiciones. [NOM-247-SE-2021 en el Diario Oficial de la Federación](https://dof.gob.mx/nota_detalle_popup.php?codigo=5646251).

Antes de producción se necesita revisión de abogado mexicano sobre aviso, base jurídica/consentimientos, REPEP, retención, transferencias entre inmobiliarias/proveedores y obligaciones estatales o profesionales aplicables. Este documento no resuelve esas cuestiones.

## Evaluación del proceso de 28 días

| Elemento | Evaluación | Riesgo | Decisión recomendada para piloto |
|---|---|---|---|
| Día 1: llamada + WhatsApp + email | La velocidad importa; tres impactos cercanos no están validados | Sensación de acoso, duplicidad, consentimientos distintos | Respuesta inmediata en el canal iniciado; un canal secundario sólo como fallback permitido |
| Días 3–10: alta intensidad | No hay evidencia inmobiliaria que valide esta secuencia | Fatiga; desde día 3 WhatsApp suele estar fuera de ventana y requiere plantilla | Probar menos contactos, cada uno con propósito distinto; máximo de presión multicanal |
| Días 14–28 | Es reactivación/nurture, no servicio continuo por defecto | Marketing sin opt-in, bloqueo/reporte, contacto irrelevante | Sólo opt-in de marketing vigente y valor nuevo; salida fácil en cada plantilla |
| `SI (2)` y `DIA 22 (2 A)` | Semántica no definida | Dos mensajes/llamadas accidentales o implementación equivocada | Aclarar si significa segundo intento, dos contactos o dos agentes |
| “Archivar” en día 28 | Útil como estado operativo | Confundir archivo con borrado, o con permiso de campañas futuras | `dormant/lost` con motivo, próxima condición de reactivación y retención separada |
| “Soft appointment +72 h” | Ambiguo | Contactar después de una cita que quizá ocurrió, se canceló o cambió | Definir significado y condicionar por estado observado |
| “Solid appointment -72 h” | Compatible con evidencia análoga de recordatorios | Un recordatorio no garantiza asistencia | Probar T-72 h y T-24 h con confirmar/reprogramar/cancelar |
| Confirmación gerencial el día de la cita | Puede reducir fallas operativas | Demasiado tarde si dirección/agente no están claros; duplicidad | Confirmación interna previa y mensaje al cliente sólo si aporta algo necesario |

### Cadencia piloto propuesta, no adoptada

La alternativa no es abandonar el seguimiento, sino volverlo **adaptativo**:

1. **Entrada:** acuse útil inmediato en el canal de origen; recuperar contexto previo y registrar el objetivo actual sin volver a preguntar todo.
2. **Conversación activa:** mientras el usuario responde, actuar dentro de la ventana de servicio y avanzar a propiedad relevante, calificación mínima, humano o cita.
3. **Silencio temprano:** uno o dos follow-ups que aporten información distinta, no “sólo dando seguimiento”. La cantidad y separación deben probarse.
4. **Cita:** recordatorios experimentales a T-72 h y T-24 h; detener al cancelar o reprogramar.
5. **Dormancia:** cerrar el ciclo con motivo explícito. No seguir por calendario.
6. **Reactivación por nueva propiedad:** disparar sólo ante una coincidencia explicable y suficientemente fuerte, disponibilidad verificada, opt-in de recomendaciones vigente, límites de frecuencia y ausencia de supresión.
7. **Campaña de desarrollo nuevo:** audiencia con consentimiento específico, segmentación por necesidad real, plantilla de marketing aprobada, cupo por ola, grupo de control y corte automático por señales negativas.

La secuencia exacta debe salir de datos propios mediante un piloto pequeño; no debe codificarse como verdad universal.

## Contrato de estado y controles que necesita el CRM

El CRM debería distinguir al menos:

- `lead_status`: nuevo, conversando, calificado, cita tentativa, cita confirmada, visitó, oferta, ganó, perdió, dormido, no contactar;
- `owner` y `next_action_at`: ningún lead activo puede quedar sin ambos;
- `intent_snapshot`: operación, zonas, presupuesto/rango, recámaras, baños, características indispensables/preferidas y horizonte, cada dato con procedencia y vigencia;
- `consent_ledger`: canal, categoría, alcance, fuente/texto, fecha, versión del aviso, revocación y evidencia;
- `suppression`: WhatsApp, llamada, email y global, con razón y momento;
- `contact_event`: planeado, permitido/denegado, plantilla, enviado, entregado, leído cuando esté disponible, respondido, fallo, bloqueo/queja y agente/automatización responsable;
- `property_match`: criterios satisfechos/fallidos, datos verificados, propiedad propia/compartida y explicación entregable;
- `outcome`: cita realizada/no-show, oferta, compra/no compra y motivo conocido, sin convertir ausencia de compra en juicio sobre la persona;
- `experiment_assignment`: política, variante y versión para medir causalmente sin cambiar el tratamiento a mitad del ciclo.

Controles deterministas previos a cualquier envío:

```text
identidad resuelta
  -> consentimiento válido para canal y categoría
  -> no existe opt-out / supresión / REPEP aplicable
  -> finalidad compatible con aviso de privacidad
  -> estado del lead permite contacto
  -> valor nuevo o acción concreta
  -> ventana de 24 h o plantilla aprobada correcta
  -> presupuesto de frecuencia multicanal disponible
  -> horario permitido y zona horaria conocida
  -> disponibilidad y datos de propiedad verificados
  -> idempotencia y auditoría
  -> enviar o crear tarea humana
```

El “horario permitido” no debe presentarse como una “mejor hora” científicamente demostrada. Al inicio debe ser una política conservadora de cortesía y cumplimiento; después puede optimizarse con datos propios, respetando preferencias explícitas del cliente.

## Medición: demostrar que Maia evita perder leads

### Métrica principal de operación

**Cobertura de seguimiento accionable:** proporción de leads activos que tienen identidad resuelta, dueño, estado actualizado y una próxima acción no vencida.

Esta métrica ataca directamente el problema de negocio sin incentivar spam. Debe acompañarse de una cola de excepciones: leads sin asignar, SLA vencido, conversación esperando humano, cita sin confirmar, fallo de entrega y follow-up bloqueado por falta de consentimiento.

### Embudo de negocio

- latencia hasta primera respuesta humana o automática **útil**;
- contacto bidireccional, no sólo entrega;
- calificación con necesidad vigente;
- cita agendada, confirmada y realizada;
- oferta y cierre;
- tiempo por etapa y motivo de pérdida;
- reactivación que produce conversación, visita, oferta y cierre incremental.

### Métricas de daño y confianza

- opt-out por mensaje y por 1,000 destinatarios;
- bloqueos/reportes o indicadores de calidad que Meta exponga;
- plantillas pausadas/rechazadas;
- contactos enviados después de una respuesta, cancelación o cierre;
- duplicados entre canales;
- quejas, errores de identidad y propiedades no disponibles o mal descritas;
- mensajes sin información nueva.

### Diseño de prueba

Para comparar la cadencia aportada con una adaptativa:

1. Definir población, fuente del lead, consentimiento y resultado primario antes de iniciar.
2. Aleatorizar por lead —no por mensaje— entre una versión conservadora y la cadencia candidata.
3. Mantener plantillas, reglas de elegibilidad y ventana de medición versionadas.
4. Medir citas **realizadas** o avances de etapa, no aperturas; incluir opt-out y bloqueo como guardrails.
5. Conservar un grupo sin campaña para reactivaciones masivas y medir incremento, no conversiones que habrían ocurrido de todos modos.
6. Detener una variante si supera umbrales predefinidos de daño o calidad, aunque genere más respuestas.
7. No optimizar “hora” o frecuencia sobre muestras pequeñas; reportar intervalos de confianza y efectos por fuente/segmento sólo cuando haya potencia suficiente.

## Preguntas que siguen abiertas

1. ¿Qué significan exactamente `SI (2)`, `DIA 22 (2 A)`, `soft appointment +72 horas` y `solid appointment -72 horas`?
2. ¿Los leads de Facebook aceptaron solamente ser contactados por el inmueble anunciado o también seguimiento general, llamadas, correo, recomendaciones y nuevos desarrollos?
3. ¿Quién será legalmente el responsable de los datos: la inmobiliaria propia, el agente asociado, una inmobiliaria cliente de la plataforma o una combinación? Esto cambia aviso, transferencias y arquitectura multi-tenant.
4. ¿Cómo se comprobará REPEP antes de llamadas/publicidad y con qué frecuencia se actualizará la supresión?
5. ¿Qué fuentes permiten afirmar disponibilidad, precio y comisión de una propiedad compartida, y cuánto tiempo se considera fresca esa verificación?
6. ¿Qué evento y qué umbral convierten una coincidencia de propiedad en razón legítima para reactivar a alguien?
7. ¿Cuánto tiempo se conservarán identidad, conversación, preferencias, consentimiento, resultados y analítica? ¿Qué debe anonimizarse o borrarse en cada etapa?
8. ¿Qué resultado de negocio justificará ampliar el piloto y qué tasa de opt-out/bloqueo lo detendrá?
9. ¿Qué horario de cortesía se adoptará inicialmente y cómo se respetará la preferencia individual del lead?
10. ¿Cuál es la obligación profesional y regulatoria exacta de la futura inmobiliaria y de sus agentes en cada estado mexicano donde opere?

## Fuentes y límites

Se priorizaron normas y políticas oficiales vigentes, publicaciones revisadas por pares y la fuente original de un benchmark comercial conocido. No se usaron blogs de agencias para declarar frecuencias, cantidades de intentos o “mejores horarios”. La evidencia experimental de recordatorios procede de salud y sólo se usa como analogía explícita. No se localizó evidencia causal específica de una cadencia inmobiliaria por WhatsApp en México; esa ausencia es precisamente la razón para instrumentar y experimentar antes de automatizar a escala.
