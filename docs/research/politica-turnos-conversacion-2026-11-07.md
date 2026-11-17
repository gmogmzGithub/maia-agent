# Política de turnos de Maia

Fecha: 7 de noviembre de 2026. Investigación y propuesta para discusión. No modifica código, skills ni acuerdos aprobados.

Los acuerdos posteriores con Guillermo y el diseño general del loop se consolidaron en [Comportamiento conversacional y loop de Maia](../design/harness-conversacional.md). Este informe conserva la investigación original; los ejemplos del diseño siguen pendientes de validación.

## Conclusión

Maia necesita elegir un siguiente paso pertinente y ceder el turno. Añadir una pregunta de nombre al final de otra decisión crea dos demandas competidoras. Obligar a pedir el nombre primero convertiría esa fricción en un formulario.

Recomendación: una petición principal por respuesta, aceptar todos los datos que el cliente dé y permitir que cambie la dirección. Pedir el nombre en un momento oportuno, sin interrumpir una duda ni bloquear una visita. Esta política es una propuesta para Maia, no una secuencia validada científicamente para ventas inmobiliarias.

## Evidencia y límites

| Fuente primaria | Hallazgo | Límite de aplicación |
|---|---|---|
| [Google: preguntas](https://developers.google.com/assistant/conversation-design/questions) | Recomienda una pregunta por turno y esperar la respuesta. Las preguntas acotadas facilitan responder; usarlas en exceso vuelve la interacción tediosa. | Guía de diseño, principalmente para Assistant; no demuestra qué secuencia convierte más prospectos. |
| [Google: comandos](https://developers.google.com/assistant/conversation-design/commands) | Recomienda adaptar la interacción al lenguaje del usuario y permitir tanto diálogos graduales como solicitudes con varios datos juntos. | No prescribe nuestra política comercial ni un nombre obligatorio. |
| [Google Chat: necesidades, voz y tono](https://developers.google.com/workspace/chat/audience#voice_and_tone) | Recomienda mensajes breves, considerados y enfocados; una llamada a la acción por mensaje. La aplicación puede hablar coloquialmente sin fingir ser humana. | Orientación para aplicaciones de texto, no estudio de compradores mexicanos. |
| [Radlinski y Craswell, 2017, secciones 3 y 6](https://www.microsoft.com/en-us/research/wp-content/uploads/2017/01/radlinski2017conversational.pdf) | Propone búsqueda con iniciativa compartida y memoria: tanto usuario como sistema pueden dirigir el intercambio y reutilizar preferencias anteriores. | Marco teórico de recuperación de información. No valida agendamiento, captura de teléfonos o un orden óptimo de preguntas. |
| [Jurafsky y Martin, borrador de agosto de 2024, sección 15.1](https://web.stanford.edu/~jurafsky/slp3/old_aug24/15.pdf) | Describe preguntas y respuestas como pares que generan expectativas; admite subdiálogos, aclaraciones y cambios antes de retomar una tarea. | Síntesis de lingüística y sistemas de diálogo. No obliga a contestar cada pregunta inmediatamente ni justifica insistir. |

Las guías antiguas de Assistant se usan como referencias de interacción, no como recomendación de integrar esa plataforma. En chat asíncrono no debemos convertir silencio en rechazo ni copiar tiempos de espera de voz.

## Qué falla en el ejemplo

La captura muestra una ficha con «¿Te interesa esta propiedad?» y después «Por cierto, ¿con quién tengo el gusto?». El cliente pulsa «Me interesa». Maia entonces ofrece horarios y pide celular.

El clic responde a la oferta de la ficha. No contiene un nombre ni indica que el cliente decidió negarse a compartirlo. La interfaz ofrece dos caminos de respuesta y el flujo solo continúa uno. Esta es una interpretación del caso, apoyada en la distinción entre acciones y expectativas de respuesta; no un diagnóstico técnico completo.

La skill actual contiene dos instrucciones que favorecen el problema:

- Pide usar `request_name` en el primer intercambio sobre una propiedad concreta o un interés expreso.
- Permite una decisión principal «además de la pregunta opcional del nombre».

Declarar el nombre opcional no evita que su pregunta compita con otra acción. Cambiar su redacción tampoco decide cuándo conviene pedirlo.

## Política propuesta, pendiente de acuerdo

1. Interpretar la aportación más reciente: pregunta, corrección, selección, datos o cierre.
2. Conservar todos los datos válidos ofrecidos, aunque no respondan a la pregunta esperada.
3. Responder primero a una duda o corrección pertinente. Suspender brevemente el agendamiento si hace falta.
4. Elegir una petición principal que permita avanzar. No añadir otra automáticamente.
5. Distinguir dato desconocido de dato necesario ahora. No pedir todos los campos faltantes.
6. Mantener preguntas pendientes con su propósito. Un clic de interés no responde al nombre ni confirma una cita.
7. Si el nombre falta y no hay una intención más concreta que atender, puede ser la siguiente pregunta. Si ya lo rechazó o pasó a otro asunto, continuar sin perseguirlo.
8. Antes de reservar, reunir los requisitos reales y obtener la confirmación del flujo existente. No confundir una propuesta de visita con una reserva ejecutada.

«Una petición principal» es una regla de atención, no un contador de signos de interrogación. «¿Cómo te llamas? Compárteme tu celular» contiene dos peticiones. «¿Te funciona lunes a las 10 o martes a las 4?» contiene una elección. Nombre y teléfono pueden agruparse si el usuario pide explícitamente dejar sus datos o abre un formulario; no deben acumularse por defecto con horarios y otra decisión.

La frase «Por cierto, ¿con quién tengo el gusto?» es una preferencia de Guillermo. Ninguna fuente revisada demuestra que esa formulación sea superior o que deba repetirse literalmente en todos los contextos.

## Siete escenarios para probar antes de implementar

Los horarios y datos siguientes son ficticios. En ejecución deben proceder del inventario y calendario.

| Situación | Continuación propuesta | Qué evitamos |
|---|---|---|
| Búsqueda devuelve una ficha | «Esta opción coincide con lo que buscas». Ficha con «Me interesa». | Añadir nombre y otra pregunta cuando la ficha ya ofrece el siguiente paso. |
| Clic en «Me interesa», sin nombre ni petición específica | «Claro, te ayudo a coordinar una visita. ¿Con quién tengo el gusto?» Esperar. | Nombre como coletilla, horarios y teléfono en el mismo turno. Es un posible default, no un requisito rígido. |
| «Me interesa, ¿puedo verla mañana?» | «Mañana tengo 10:00 o 12:00. ¿Cuál te funciona?» | Detener una solicitud concreta para pedir nombre antes de ayudar. |
| Maia pregunta nombre y el cliente responde «Antes, ¿aceptan perros?» | Responder con el dato confirmado. Si se desconoce: «Todavía no está confirmado si aceptan perros». Ofrecer solo una alternativa disponible si hace falta. | Repetir el nombre, inventar la respuesta o seguir vendiendo una visita sin atender la condición. |
| «Soy Ana, el lunes a las 10 me funciona y mi celular es…» | Registrar los tres datos. Avanzar al resumen y confirmación si ya están los requisitos. | Exigir un turno para cada dato o volver a pedir el teléfono. |
| «Prefiero no dar mi nombre; muéstrame horarios» | Ofrecer disponibilidad real y preguntar cuál le funciona. | Tratar el nombre opcional como bloqueo. |
| WhatsApp ya identifica el número y el cliente elige un horario | Pedir únicamente el dato que realmente falte, o pasar a confirmación. | Solicitar otro WhatsApp por costumbre o afirmar que ya se reservó. |

## Alternativas y tradeoffs

| Alternativa | Ventaja | Coste |
|---|---|---|
| Nombre primero siempre | Orden simple y predecible. | Interrumpe dudas concretas, añade fricción y contradice nombre opcional. No recomendada. |
| Horarios primero siempre | Avanza rápido hacia la cita. | Puede precipitarse ante dudas o ignorar un momento natural de presentación. Tampoco debe ser rígida. |
| Nombre añadido siempre | Captura oportunista sin turno separado. | Compite con botones y horarios; reproduce el fallo observado. No recomendada. |
| Política contextual con una petición principal | Sigue la intención, acepta atajos y deja espacio para responder. | Requiere estado conversacional, ejemplos y evaluación; el prompt aislado no garantiza cumplirla. Recomendada. |

## Cómo validarlo

[Google recomienda probar diálogos con personas antes de escribir código](https://developers.google.com/assistant/conversation-design/test-and-iterate). Para Maia, representar estos siete escenarios con Santiago y alguien ajeno al diseño; observar si saben qué responder y pueden cambiar de dirección. No hace falta construir otra interfaz.

Después, evaluar trazas completas, no respuestas aisladas: intención atendida, una petición principal, datos reutilizados, preguntas no repetidas, reserva correcta y ausencia de acciones inventadas. Medir los turnos adicionales sirve para detectar fricción, pero una conversación más corta no prueba mejor atención.

Pendiente: acordar la política, revisar el estado real que el harness conserva y decidir su representación mínima. No se propone todavía otra máquina de estados completa ni otro archivo `SOUL.md`.
