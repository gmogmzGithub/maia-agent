# Descubrimiento de la plataforma

> Actualización: Guillermo autorizó iniciar la etapa 6 mediante Q275. Alcance: primer incremento, inventario desde CRM, búsqueda conversacional con Haiku, fichas y persistencia en PostgreSQL. El texto siguiente conserva el contexto histórico del inicio del descubrimiento.

## Base expresada por Guillermo

- La plataforma atenderá el inventario y la operación de una inmobiliaria; no será un mercado abierto entre inmobiliarias.
- La prioridad del negocio es facilitar que las personas del equipo no pierdan prospectos por falta de atención o seguimiento.
- Guillermo dirige la ingeniería. Santiago Mirabal aporta experiencia comercial inmobiliaria y puede resolver dudas sobre ventas y seguimiento.
- El diseño precede a la implementación. Esta sesión no autoriza código.
- El diagrama inicial está en `architecture/Architecture.png`; sus componentes son hipótesis de diseño, no tecnologías aprobadas.

## Secuencia propuesta, pendiente de acuerdo

1. Acordar alcance del producto, primer caso de uso, resultado medible y límites de responsabilidad.
2. Recorrer casos completos, incluyendo interrupciones, intervención humana y fallos.
3. Derivar capacidades y módulos lógicos, sus responsabilidades y conexiones.
4. Profundizar por módulo; estudiar Hermes y Waku cuando exista una pregunta concreta que resolver.
5. Elegir tecnologías y definir contratos técnicos, trazas y criterios de evaluación.
6. Implementar recorridos completos por etapas, una vez autorizada la implementación.

## Preguntas abiertas de la primera ronda

- ¿El producto atenderá varias inmobiliarias aisladas entre sí, comenzando por una, o una sola inmobiliaria en total?
- ¿Qué recorrido debe resolver la primera entrega utilizable?
- ¿Qué situación concreta contará como un prospecto perdido por falta de atención o seguimiento?
- ¿Qué compromisos podrá asumir el agente por sí mismo y cuáles requerirán confirmación humana?

## Pendientes para rondas posteriores

- Flujo de captación de propiedades y autorización para incorporarlas al inventario.
- Búsqueda conversacional y relación con otros mecanismos de búsqueda.
- Responsabilidades comerciales y fuentes de información autorizadas.
- Memoria funcional, persistencia y procedimientos del agente.
- Seguimiento: duración, frecuencia, condiciones de entrada, pausa y cierre.
- Acompañamiento posterior a la intención de compra o renta.
- Calidad, observabilidad, evaluación y diagnóstico.
- Tecnologías y límites entre decisiones deterministas y tareas del LLM.
