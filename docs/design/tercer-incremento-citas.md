# Tercer incremento: citas con Google Calendar

Estado al 6 de noviembre de 2026: cerrado con validación de Guillermo. Google está conectado. Guillermo reportó las pruebas manuales exitosas y confirmó que funciona la corrección que ofrece horarios sin pedir primero una fecha. Pasaron 72 pruebas de backend y la compilación del frontend. Haiku real consultó sin fecha y ofreció tres horarios con resultados de herramienta controlados.

## Base acordada

Google Calendar es el único proveedor. El CRM configura las ventanas semanales por propiedad y la duración de las citas, con una hora por defecto. Maia interpreta solicitudes; el código valida disponibilidad y ejecuta las operaciones. Una cita solo se confirma tras verificar su creación.

El celular debe quedar confirmado mediante el flujo existente antes de crear una cita. El número sigue siendo declarado, sin verificar identidad ni habilitar acceso a otras conversaciones.

## Responsables y disponibilidad

- **C1:** agendar en el calendario del asesor de la propiedad. Conservar al responsable del prospecto. Avisar a ambos por Telegram, una sola vez si coinciden.
- **C2:** anticipación mínima de dos horas, configurable para toda la inmobiliaria desde el CRM.
- **C3:** horizonte de reserva de 14 días, configurable desde el CRM. Registrar solicitudes posteriores para atención humana.
- **C6:** sin tiempo obligatorio adicional entre visitas. El asesor bloquea sus traslados y compromisos en Calendar.
- **C10:** permitir varias citas por prospecto. Cada cita conserva propiedad, asesor, horario y resultado. Impedir superposiciones del prospecto y reservas duplicadas.
- **C14:** ventanas configurables por propiedad. Valor inicial: lunes a viernes, de 10:00 a 14:00 y de 16:00 a 19:00. Toda la cita debe caber en una ventana y en un periodo libre del asesor. Usar hora de Guadalajara y mostrarla al confirmar.
- **C16:** impedir visitas simultáneas a una propiedad. Asesor, prospecto y propiedad deben estar disponibles durante toda la cita.
- **C17:** ante una solicitud de visita a una propiedad conocida, consultar y ofrecer hasta tres horarios reales antes de preguntar preferencias. Sin fecha indicada, buscar los próximos disponibles dentro del horizonte. Ofrecer inicios cada 30 minutos. El prospecto puede pedir otras opciones o proponer una hora, que se valida antes de reservar.
- **C21:** si la propiedad no tiene asesor, usar al predeterminado del CRM. Si tampoco existe, guardar la solicitud sin confirmar cita.

## Creación y cambios

- **C4:** mostrar propiedad, fecha, hora y duración; pedir confirmación explícita. Revalidar disponibilidad al confirmar. Ofrecer un horario no lo reserva.
- **C5:** cuando no haya horarios, preguntar la preferencia, registrarla en CRM y avisar al asesor. La solicitud queda pendiente, sin cita confirmada.
- **C7:** el prospecto puede cancelar o reprogramar citas creadas en su conversación original, previa confirmación. Desde otra conversación interviene el asesor. Declarar el mismo celular no demuestra identidad.
- **C8:** gestionar las citas de Maia desde el CRM durante esta versión. El asesor puede bloquear otros tiempos en Calendar. Ante diferencias detectadas en una cita, solicitar revisión humana sin sobrescribir automáticamente. Falta definir técnicamente cómo detectar esas diferencias.
- **C11:** ante fallos de Calendar, guardar la solicitud, informar que no está confirmada y avisar al asesor. Si el resultado de creación es desconocido, verificar antes de reintentar.
- **C13:** el asesor también puede crear citas desde el CRM, con las mismas reglas de disponibilidad y sin excepciones.
- **C18:** cambios de ventanas, duración o asesor aplican a nuevas reservas. Las citas confirmadas conservan sus datos originales; modificarlas requiere reprogramación explícita.
- **C19:** despublicar impide nuevas reservas, conserva las citas existentes y avisa al asesor para que decida. No cancela automáticamente ni envía una cancelación al prospecto.
- **C22:** permitir cancelaciones aunque falten menos de dos horas. Reprogramar exige que el nuevo horario cumpla anticipación y disponibilidad. Conservar la cita original hasta verificar el cambio.

Reprogramar es una operación de negocio, no una cancelación seguida de una creación organizada por el modelo. Registrar el intento antes de llamar a Google y conservar una referencia recuperable. La transacción de PostgreSQL no abarca Google Calendar. Ante un resultado desconocido, verificar la misma operación antes de repetirla. Estos contratos se acordaron en Q255–Q259.

## CRM y notificaciones

- **C9:** el asesor registra Realizada o No asistió. El fin del horario no demuestra asistencia. Cancelar una cita no marca al prospecto como Sin interés.
- **C12:** confirmar en el website y notificar al asesor por Telegram. Los recordatorios al prospecto quedan para la integración de WhatsApp.
- **C15:** añadir la etapa comercial Cita agendada. Al cancelar, volver a En atención si no quedan otras citas futuras.
- **C20:** al registrar Realizada o No asistió, usar En atención, salvo que queden otras citas futuras. El asesor registra el siguiente paso.

Las citas conservan su resultado separado de la etapa comercial del prospecto. Crear, modificar o cancelar actualiza Calendar, CRM y avisos sin duplicar la operación por un fallo de notificación.

## Acuerdos técnicos

- **T1:** coordinar reservas propias por asesor, propiedad y prospecto. La primera reserva que termina correctamente conserva el horario; las siguientes revalidan disponibilidad. Registrar la coordinación en PostgreSQL sin mantener una transacción abierta durante llamadas a Google. Esto no garantiza exclusión frente a cambios externos de Calendar.
- **T2:** ante un resultado desconocido, conservar la operación pendiente de verificar y el horario temporalmente ocupado en Maia. Consultar Google mediante una referencia de la operación antes de repetirla. Si no se resuelve, pedir revisión humana. Estos estados técnicos no son etapas comerciales.
- **T3:** OAuth por asesor desde el CRM. El backend conserva y renueva la autorización; el LLM no recibe credenciales. Revisar la configuración OAuth del piloto: External + Testing con permisos de Calendar caduca a los siete días. La etapa Beta del producto no obliga a usar Testing de Google.
- **T4:** consultar disponibilidad y crear visitas en el calendario principal del asesor. Sin selector ni consulta de calendarios secundarios en esta versión. Los compromisos que bloqueen visitas deben aparecer como ocupados en el principal.
- **T5:** ante pérdida de acceso, conservar las citas registradas, mostrar Reconectar Google Calendar y bloquear nuevas confirmaciones del asesor. No transferir automáticamente solicitudes. Las cancelaciones y reprogramaciones quedan pendientes hasta verificar su aplicación en Google.
- **T6:** conservar el calendario principal con conocimiento del alcance amplio de OAuth. El backend consulta compromisos ajenos solo como intervalos ocupados y accede a detalles únicamente de eventos registrados como citas de Maia. Las herramientas del LLM reciben referencias de citas del CRM, no identificadores arbitrarios de Google. Esta restricción es del código; el permiso de Google no queda limitado a eventos de Maia.
- **T7:** consultar cada cinco minutos los eventos futuros registrados por Maia y comprobarlos antes de modificar o cancelar. No incorporar canales push de Google en el piloto.
- **T8:** ante una modificación externa o desaparición, marcar Requiere revisión, conservar datos originales, mostrar la diferencia y avisar al asesor. Detener cambios automáticos sobre esa cita hasta resolverla. No comunicar una modificación al prospecto sin confirmar qué corresponde. Un error de consulta por sí solo no demuestra eliminación.
- **T9:** verificar resultados desconocidos una vez por minuto durante cinco minutos, mediante consultas, sin crear eventos nuevos. Si no se resuelve, conservar el pendiente y bloqueo del horario en Maia, y avisar al asesor. No liberar el horario suponiendo fallo.
- **T10:** resolver diferencias desde el CRM mediante Aceptar el cambio de Google o Restablecer desde el CRM. Validar disponibilidad y reglas antes de aceptar otro horario o restablecerlo; si no cumple, elegir otro. Una eliminación requiere confirmar la cancelación. Guardar la resolución y notificar responsables.
- **T11:** mantener la administración actual del CRM. Un usuario staff selecciona la ficha del asesor e inicia Conectar Google Calendar; el propietario autoriza su cuenta en Google. Mostrar la cuenta resultante y confirmar su asignación. Registrar quién inició la conexión. No añadir usuarios individuales, invitaciones ni roles por asesor. Conectar Google no inicia sesión en el CRM ni demuestra que la cuenta corresponda al asesor seleccionado.

Para recuperar creaciones, registrar un identificador de evento estable antes de llamar a Google y consultar ese mismo identificador si se pierde la respuesta. No generar otro identificador para reintentar la misma operación. Un 404 aislado no demuestra que nunca se creó: también puede indicar falta de acceso.

Fuentes: [OAuth y renovación](https://developers.google.com/identity/protocols/oauth2/web-server), [modo Testing](https://support.google.com/cloud/answer/15549945?hl=en), [consulta de disponibilidad](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query), [permisos](https://developers.google.com/workspace/calendar/api/auth), [identificadores de creación](https://developers.google.com/workspace/calendar/api/guides/create-events), [notificaciones push](https://developers.google.com/workspace/calendar/api/guides/push), [errores](https://developers.google.com/workspace/calendar/api/guides/errors).

## Preparación de implementación

La implementación conserva Django, PostgreSQL, el worker y las responsabilidades de [organización del código](../architecture/code-structure.md). No requiere otra cola ni otro servicio.

1. Persistencia: conexión del calendario por asesor, ventanas por propiedad, configuración global, citas, operaciones y referencias de Google. Separar resultado de visita, estado técnico y etapa comercial.
2. Conexión: callback vinculado al asesor y sesión staff que lo inició, confirmación de cuenta, renovación y desconexión. Guardar tokens cifrados en backend; mantener la clave fuera de la base de datos y del repositorio. Nunca enviar credenciales al frontend, al LLM ni a los logs. La pérdida de la clave requiere reconectar las cuentas.
3. Reservas: reglas deterministas de disponibilidad, coordinación local durable y operaciones recuperables. Ejecutar HTTP fuera de transacciones. Los cambios de eventos deben comprobar su versión para no sobrescribir una edición externa concurrente. Ningún bloqueo local impide que una persona modifique Google durante una reserva.
4. Worker: creación, modificación, cancelación, recuperación, revisión periódica y notificaciones. Reutilizar la entrega Telegram; un fallo del aviso no repite la reserva.
5. API y pantallas: acciones públicas limitadas a la conversación original y operaciones privadas del CRM con los permisos staff existentes. Mostrar confirmación final de la cita y pendientes de revisión. El LLM solicita acciones concretas; no modifica reglas, credenciales ni identificadores Google arbitrarios.
6. Validación: probar conflictos entre reservas, confirmaciones repetidas, aislamiento entre conversaciones, desconexión, resultados desconocidos, cambios externos y fallos de notificación. Completar pruebas existentes, migraciones, contrato OpenAPI, compilación del frontend y recorrido real con Google y Telegram.

Antes del recorrido real, configurar el proyecto Google, los permisos y el callback del dominio HTTPS o localhost correspondiente. Verificar el modo de publicación OAuth y la renovación de acceso del piloto. No dar por configurado un servicio porque existan sus variables en `.env.example`.

## Fuera de alcance

Integración de WhatsApp, recordatorios al prospecto, seguimiento de 28 días, acompañamiento posterior a la intención y captación de propiedades.
