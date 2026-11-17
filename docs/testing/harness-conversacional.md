# Pruebas del harness conversacional

Estado: implementación del contrato y pruebas automáticas. La aceptación manual de naturalidad y presentación sigue pendiente.

Verificación del contrato original: 183 pruebas aprobadas y dos opcionales omitidas; prueba real separada de Haiku aprobada; Ruff, Django, TypeScript, compilación y proxy correctos. Migración `0007` aplicada. No se enviaron mensajes de prueba a WhatsApp ni Telegram.

## Reorganización de los cuatro bloques

El [mapa actual de archivos](../architecture/harness/code-map.md) registra memoria funcional, aceptación y presentación, herramientas y ciclo del chat.

- Backend: **187 pruebas aprobadas, dos opcionales omitidas**. Incluye aceptación y formato sin consultas, con propuestas propias y límites de WhatsApp.
- Website: **seis pruebas aprobadas** mediante `pnpm test`. Cubren restauración antes del interés, doble clic, borrador, reintento con el mismo identificador, polling, respuestas tardías y desmontaje.
- Ruff y comprobación Django aprobados; `makemigrations --check --dry-run` no detectó cambios.
- TypeScript y compilación de producción aprobados.
- OpenAPI idéntico entre backend anterior, backend reorganizado y contrato publicado del frontend. Modelos, esquemas, migraciones e instrucciones conservan sus contenidos.
- Proxy real aprobado mediante `backend/scripts/check_web_routes.py`: creación HTTP 200 y lectura de conversación por el website, con sesión y CSRF.

El proxy se comprobó con las imágenes nuevas en un entorno desechable, sin credenciales de proveedores ni worker. La plataforma donde Guillermo ejecuta pruebas manuales no se reinició. Las pruebas reales opcionales de proveedores no se repitieron durante esta reorganización.

Para probar el ciclo del website desde la raíz del proyecto con Node y dependencias instaladas:

```sh
cd /Users/el-men/Workspace/maia-agent/frontend
pnpm test
```

Esta verificación demuestra conservación técnica del contrato; no sustituye los recorridos de naturalidad siguientes.

## Recuperación inesperada tras «Me interesa», 7 de noviembre de 2026

La ejecución reportada guardó dos rechazos `ValueError` y `error_code=reply_recovery`, sin motivo específico. Su causa exacta no puede reconstruirse con esa traza. Siete repeticiones de solo lectura del mensaje original no reprodujeron el fallo con Haiku.

Una prueba controlada reprodujo el texto exacto de recuperación cuando el proveedor devuelve texto libre tanto en la respuesta como en su corrección. El harness exigía `propose_reply` mediante instrucciones, pero dejaba `tool_choice` en el valor predeterminado de la API.

La petición ahora usa `tool_choice=any` durante el loop y selecciona explícitamente `propose_reply` durante la corrección. El modelo sigue decidiendo qué herramienta necesita; la corrección continúa sin permiso para ejecutar operaciones comerciales. Se conserva la validación de fichas, controles y vigencia. [Contrato del proveedor](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools#forcing-tool-use).

Los rechazos guardan `reason`, `stop_reason` y nombres de herramientas reconocidas en `Execution.tool_events`, además de emitir un log `reply_rejected`. Las razones son códigos permitidos; no incluyen texto del modelo, valores de validación ni datos personales. La traza distingue salida sin herramienta, ficha no autorizada y visita sin propuesta vigente.

Verificación: **191 pruebas aprobadas y dos opcionales omitidas**, Ruff y Django correctos, sin migraciones nuevas. La prueba controlada pasó de fallo a éxito. Una repetición real del mensaje terminó correctamente; una prueba separada con Haiku de interés, interrupción y nombre también pasó, sin envíos WhatsApp o Telegram. La repetición del mensaje usó lectura del inventario y hechos de interés ya registrados, sin nuevas escrituras comerciales.

La prueba manual pendiente consiste en continuar el chat afectado. No se reenvía automáticamente la respuesta fallida ni se inventa el motivo de su rechazo original.

## Preparación

Usar conversaciones nuevas y propiedades publicadas de prueba. Los mensajes anteriores conservan su formato. El nuevo contrato usa la migración `0007_message_reply_contract`; no reescribe el historial.

## Recorridos manuales

1. Buscar una propiedad. Comprobar fichas compactas y texto breve, sin repetir sus datos.
2. Pulsar «Me interesa». Comprobar envío inmediato, sin burbuja ficticia ni ficha repetida. Maia debe dejar espacio para responder a la petición principal que elija.
3. Si pregunta el nombre, responder con una duda sobre mascotas. Debe atenderla sin repetir automáticamente el nombre ni mostrar un formulario de celular ajeno a esa respuesta.
4. Pedir una visita para una fecha concreta. Debe consultar y ofrecer horarios reales, sin bloquear con el nombre opcional.
5. Elegir horario y proporcionar varios datos juntos. Debe aprovecharlos y pedir únicamente la confirmación necesaria. En website, declarar un número no lo confirma.
6. Confirmar el celular desde el formulario. Debe retomar el horario elegido y presentar una propuesta de visita válida antes de reservar.
7. Desde WhatsApp, comprobar que no vuelve a pedir el número del remitente. Una propuesta de visita solo muestra botón cuando esa respuesta lo incluye.
8. Interrumpir una confirmación pendiente con otra duda. El botón no debe adjuntarse automáticamente a esa respuesta.
9. Recargar y continuar. Debe conservar datos y continuidad sin repetir fichas o preguntas conocidas.
10. Rechazar el nombre o despedirse. Debe respetarlo, sin bloquear la atención ni abrir otra pregunta comercial al cerrar.

Repetir presentación en desktop, iPad y móvil. Comprobar formularios, desplazamiento, teclado y ausencia de controles duplicados. Revisar los diálogos con criterio comercial; no exigir frases literales ni interpretar el nombre opcional como paso obligatorio.

## Cobertura automatizada

`backend/tests/test_turn_contract.py` cubre selección, continuidad, interrupción, datos conjuntos, referencias de controles, publicación por canal, entrega tardía y recuperación sin nuevas escrituras. Las pruebas existentes conservan autorización, pausas, idempotencia, inventario y operaciones de citas.

Las respuestas programadas comprueban el contrato y sus efectos, no prueban que el modelo elija siempre la mejor continuación. La prueba opcional real de Haiku comprueba interés, interrupción y nombre aportado en una base de pruebas, con envíos WhatsApp deshabilitados y aceptación del proveedor simulada localmente. No acredita entrega real ni toda la naturalidad comercial.

Observación de las muestras iniciales con Haiku: ante interés genérico eligió preguntar si quería visitar o resolver dudas, en vez de pedir el nombre. La comprobación anterior exigía siempre preguntar el nombre y no pasó. Se sustituyó por comprobaciones del contrato, interrupción, datos reutilizados y nombre aportado, coherentes con el nombre opcional. D02 queda pendiente de aceptación con el modelo real; no se declara validada esa preferencia comercial por haber pasado las pruebas técnicas.

Consultar los eventos `reply_validation` de la ejecución: propuesta aceptada, rechazo, corrección y pendiente anterior/nuevo. `reply_recovery` indica recuperación tras agotar una corrección. Una reserva y su resultado persistente deben revisarse por separado de un fallo de redacción o transporte.

## Límites

El nuevo contrato se aplica a conversación entrante del website y WhatsApp. No cambia automáticamente las plantillas aprobadas de seguimiento. No añade SQLite, vectores, compresión, otro agente ni un juez LLM por turno.
