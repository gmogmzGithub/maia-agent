# Comunicación humana de Maia

Fecha: 7 de noviembre de 2026. Investigación documental para mejorar las skills existentes. La validación posterior con Haiku se documenta al final; no se enviaron mensajes a clientes.

## Recomendación

Ampliar `comunicacion-humana` con reconocimiento concreto, continuidad, preguntas graduales y reparación. Mantener `comunicacion-cliente` como base de claridad y concisión. Humanizar significa atender mejor la intención del cliente, sin añadir muletillas, familiaridad forzada ni promesas. La separación entre ambas skills es una propuesta para Maia.

Google Chat recomienda mensajes claros, considerados y orientados a una acción; permite lenguaje coloquial y rechaza fingir que la aplicación es humana. [Google Chat: voz y tono](https://developers.google.com/workspace/chat/audience#voice_and_tone).

## Patrones aplicables

| Patrón | Aplicación propuesta a Maia | Fuente |
|---|---|---|
| Reconocer sin automatismos | Reflejar la decisión relevante: «Busquemos algo con jardín». No empezar cada turno con «Perfecto», «Claro» o el nombre del cliente. A veces basta responder directamente. | [Google: reconocimientos](https://developers.google.com/assistant/conversation-design/acknowledgements). |
| Aprovechar lo ya dicho | Conservar presupuesto, zona, mascotas y cambios. No pedir de nuevo datos disponibles. Entender «la segunda» usando las fichas realmente mostradas. | [Google: contexto y cooperación](https://developers.google.com/assistant/conversation-design/learn-about-conversation), [Microsoft: interacción, guía 12](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/). |
| Una decisión principal por turno | Responder primero a la duda. Después pedir el dato que desbloquea el paso siguiente. Evitar pedir presupuesto, zona, teléfono y nombre juntos. Si el cliente ya dio todo, avanzar sin interrogarlo. | [Google: preguntas](https://developers.google.com/assistant/conversation-design/questions), [Google Chat: eficiencia](https://developers.google.com/workspace/chat/audience#voice_and_tone). |
| Ofrecer límites útiles | Para una búsqueda vaga, empezar por «¿Buscas comprar o rentar?». Para una visita, ofrecer opciones que el calendario haya devuelto. Las opciones ayudan, pero deben permitir que el cliente proponga otra alternativa. | [Google: preguntas amplias y acotadas](https://developers.google.com/assistant/conversation-design/questions). La disponibilidad real procede del diseño determinístico de Maia. |
| Empatía proporcional | Ante «me urge mudarme», reconocer la urgencia y ayudar: «Busquemos opciones para tu fecha de mudanza». Ante una cancelación rutinaria, resolver sin dramatizar ni celebrar. No atribuir emociones que el cliente no expresó. | Adaptación de [Google: disculpas y soluciones](https://developers.google.com/assistant/conversation-design/apologies) y [Microsoft: relevancia y normas sociales, guías 4 y 5](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/). |
| Reparar sin reiniciar | Si corrige «renta, no compra», actualizar solo ese requisito. Si hay ambigüedad, preguntar por ese punto. Si falla el calendario, explicar el límite brevemente y ofrecer un siguiente paso disponible. | [Google: errores](https://developers.google.com/assistant/conversation-design/errors), [Microsoft: corrección eficiente](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/). |
| Confirmar el resultado correcto | Diferenciar propuesta, acción pendiente y resultado realizado. «Tu visita quedó cancelada» solo después del éxito. Las confirmaciones deben permitir corregir errores sin repetir cada dato en todos los turnos. | [Google: confirmaciones](https://developers.google.com/assistant/conversation-design/confirmations). |
| Respetar la iniciativa del cliente | Si pide información antes de visitar, responderla. Si rechaza compartir su nombre, seguir sin insistir. Si se despide, cerrar sin otra pregunta comercial. | [Google: cierres](https://developers.google.com/assistant/conversation-design/endings), [Microsoft: descarte y corrección, guías 8 y 9](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/). |
| Sonar natural sin fabricar una persona | Usar español de México cercano y profesional, sin exceso de diminutivos, emojis o entusiasmo. No inventar experiencias personales, visitas realizadas ni relaciones con el cliente. Si pregunta, identificar a Maia como asistente virtual. | La autenticidad y transparencia proceden de [Google Chat](https://developers.google.com/workspace/chat/audience#voice_and_tone) y [Microsoft: capacidades, guía 1](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/). Registro regional y límites de familiaridad: propuesta para Maia. |

Los ejemplos son patrones, no respuestas literales obligatorias. La variación debe corresponder al contexto; sustituir «Perfecto» por sinónimos al azar no demuestra atención.

## Skill frente a harness

La skill define tono, orden y ejemplos. El harness aporta hechos verificables: requisitos conocidos, pregunta de nombre ya realizada, ficha mostrada, estado de la cita, disponibilidad y resultado de herramientas. La redacción no debe inventar esos estados. Esta distribución es una recomendación de diseño para Maia, no un resultado de las fuentes.

## Casos de validación propuestos

No ejecutados. Evaluar tanto lenguaje como acciones; una respuesta agradable que pierde un requisito o inventa una reserva falla.

| Caso | Resultado esperado |
|---|---|
| «Quiero rentar en Zapopan, hasta $30,000, con dos perros» | Utiliza los tres requisitos. Pregunta solo por la siguiente carencia útil, sin repetir el cuestionario. |
| «Renta, no compra» | Corrige la operación, conserva zona y presupuesto, continúa sin culpar ni pedir todo otra vez. |
| «Me interesa», con ficha ya mostrada | Propone horarios reales. No repite ficha ni muestra texto artificial del cliente. |
| Falta nombre y nunca se preguntó | Usa «Por cierto, ¿con quién tengo el gusto?» en un momento oportuno. Si ya se preguntó y no respondió, no insiste. |
| «Primero dime si aceptan mascotas» durante el agendamiento | Responde con el dato disponible o reconoce que falta. No fuerza la selección de horario. |
| «Se me complicó, cancela la visita» | Tono considerado; conserva la confirmación del flujo existente. Anuncia la cancelación solo tras ejecutarla. |
| Calendario no responde | Explica que no pudo consultar horarios; no inventa disponibilidad, reserva ni contacto humano ya realizado. |
| «Gracias, por ahora no»; después «¿eres una persona?» | Respeta el cierre. Si el cliente retoma y pregunta por identidad, responde que es un asistente virtual, sin fingir ser asesor humano. |

## Alcance de la evidencia

Las guías de Conversation Design incluyen interacciones de voz y componentes visuales de Actions on Google. Se usan como referencias de diseño, no como recomendación de integrar esa plataforma. Sus reglas de turnos se adaptan al chat de Maia; no se trasladan tiempos de micrófono ni repreguntas por silencio.

Google Chat aporta orientación específica para texto. Microsoft presenta guías generales de interacción humano-IA. Ninguna fuente prueba que estos cambios aumenten citas o satisfacción en Maia. Eso requiere revisar conversaciones del piloto, con criterios previos y sin confundir longitud o simpatía con calidad.

## Aplicación y verificación

Se conservó el cuerpo operativo de `comunicacion-humana/SKILL.md` y se añadieron siete patrones de atención natural y cuatro referencias de tono. `comunicacion-cliente` permanece como base de concisión. No se modificó el harness, contratos, modelos ni plantillas de Meta.

Un primer borrador extenso falló la prueba real de nombre y no se activó. Se volvió a la estructura original con adiciones puntuales. La versión final pasó la prueba de Haiku que pregunta el nombre, registra la respuesta y evita repetir la pregunta, con entregas externas bloqueadas. Pasaron también 171 pruebas determinísticas, con dos pruebas opcionales omitidas en ese conjunto, y Ruff.

Se revisaron seis muestras finales de redacción con Haiku: corrección de operación, rechazo de celular, despedida, mascotas desconocidas, experiencia personal y calendario fallido. Eran escenarios ficticios con estados proporcionados, sin herramientas comerciales ni escrituras en la base. Las respuestas finales no inventaron permiso de mascotas, visitas propias, reservas ni solicitudes ya ejecutadas. El rechazo no bloqueó la conversación y la despedida no añadió otra pregunta. Algunas respuestas aún repiten requisitos o explican demasiado; no se declara el tono plenamente aceptado ni una mejora cuantificada frente al original.

Ejemplos observados, no respuestas obligatorias:

- «Soy la asistente virtual, así que no he visitado la casa ni puedo saber cuánto ruido hace. El asesor puede ayudarte a comprobarlo durante una visita. ¿Quieres que lo coordinemos?»
- «Ana, por ahora no tengo confirmado si esta propiedad acepta mascotas, así que no puedo asegurarte que tus dos perros estén permitidos. ¿Quieres que un asesor lo revise antes de agendar la visita?»

Evidencia de desarrollo: `/tmp/maia-tone-results-accepted/results.json`. Estas muestras evalúan redacción aislada, no el flujo completo, canales o satisfacción. M20 en la matriz de regresiones conserva la aceptación manual pendiente.
