# Validación manual del tercer incremento

Estado: Guillermo reportó que las pruebas manuales pasaron. Google está conectado. Las casillas conservan los casos de referencia; no existe un registro individual de cada resultado.

Verificación del desarrollo al 6 de noviembre de 2026: 72 pruebas de backend aprobadas y frontend compilado. La regresión cubre consultas sin fecha, horarios ocupados, paginación y horizonte. Haiku real llamó `visit_slots` sin fecha y ofreció tres opciones con resultados controlados, sin crear reservas ni enviar avisos. Ante una búsqueda vaga preguntó si quería comprar o rentar.

Corrección validada por Guillermo: «funciona», después de actualizar la aplicación local. No se registraron resultados individuales de los dos casos siguientes.

- [ ] Pide «Quiero agendar una cita para ver este depa» con una propiedad identificada. Maia debe consultar y ofrecer hasta tres horarios reales, sin preguntar primero qué día quieres.
- [ ] Pide «Busco una propiedad». Maia debe acotar con una o dos preguntas concretas. Si ya indicaste operación, tipo o presupuesto, no debe repetirlos.

Configura [Google Calendar](google-calendar-setup.md), un asesor predeterminado y su chat privado de Telegram. Usa propiedades y prospectos identificados como PRUEBA. Todos los horarios se interpretan en hora de Guadalajara.

## Conexión y reglas

- [ ] En CRM → Asesores, conecta Google, revisa el email y confirma su asignación. La cuenta Google no inicia sesión en el CRM.
- [ ] En CRM → Citas → Configurar horarios y reglas, cambia anticipación y horizonte. En la misma sección, configura ventanas y duración por propiedad. Los valores iniciales son dos horas, 14 días, una hora y lunes a viernes de 10:00 a 14:00 y de 16:00 a 19:00.
- [ ] Bloquea un horario como ocupado en el calendario principal. Maia debe excluirlo. Los compromisos de calendarios secundarios no bloquean visitas.
- [ ] Desconecta Google. Las citas se conservan; nuevas solicitudes no se confirman. Reconecta la misma cuenta y revisa los pendientes.

## Reserva desde el website

- [ ] Pide una visita a una propiedad. Maia consulta opciones reales, ofrece hasta tres y permite pedir otras. Los inicios siguen intervalos de 30 minutos.
- [ ] Elige un horario sin haber proporcionado celular. Confirma el número con el formulario y continúa en el website.
- [ ] Revisa propiedad, asesor, fecha y duración. Antes de pulsar Confirmar visita no debe existir una reserva.
- [ ] Confirma y espera el resultado. La misma cita debe aparecer en website, Google y CRM. El prospecto pasa a Cita agendada y Telegram avisa al asesor de la propiedad y al responsable comercial, sin duplicar si coinciden.
- [ ] Recarga o repite el clic. No debe crearse otra cita.
- [ ] Reserva otra propiedad en otro horario. Ambas citas deben conservarse. Una superposición del prospecto, propiedad, asesor o calendario debe rechazarse.
- [ ] Ocupa en Calendar un horario que Maia ya ofreció y luego intenta confirmarlo. Maia debe volver a comprobarlo y no confirmar una reserva inválida.
- [ ] Pide una fecha fuera del horizonte o sin horarios disponibles. La preferencia debe quedar como solicitud pendiente para el asesor, sin cita confirmada.

## Cambios y CRM

- [ ] Crea una cita desde CRM → Citas. Debe aplicar las mismas reglas del website.
- [ ] Reprograma desde la conversación original y confirma el resumen. Conserva la cita original hasta que Google confirme el cambio.
- [ ] Cancela desde la conversación original, también con menos de dos horas de anticipación. Comprueba Calendar, CRM y Telegram.
- [ ] Declara el mismo celular desde otra ventana privada. No debe mostrar ni permitir cambiar las citas de la conversación anterior.
- [ ] Cambia ventanas, duración y asesor de una propiedad. Las citas existentes deben conservar sus datos.
- [ ] Despublica una propiedad con cita futura. Debe dejar de admitir nuevas reservas, conservar la cita y avisar al asesor.
- [ ] Cambia una cita directamente en Google. Dentro de cinco minutos debe aparecer Requiere revisión, conservar los datos originales y avisar al asesor.
- [ ] Desde el CRM acepta el cambio externo o restablece la cita. Un horario que incumple las reglas debe rechazarse. No debe sobrescribir automáticamente una edición externa.
- [ ] Después de una visita, registra Realizada o No asistió y actualiza el siguiente paso. El prospecto vuelve a En atención, salvo que conserve otra cita futura. No cambia automáticamente a Sin interés.

## Recuperación

- [ ] Comprueba que una desconexión o fallo conserva la solicitud y muestra su estado sin anunciar éxito.
- [ ] Revisa que un fallo de Telegram no cree otra cita. El aviso conserva su propio estado y reintento.

Las pruebas automatizadas cubren dos reservas concurrentes, respuestas perdidas, verificación sin repetir creaciones y bloqueos conservados ante resultados desconocidos. No provoques duplicados reales para simular un timeout. Revisa ejecuciones con `docker compose logs -f backend worker`.

WhatsApp y recordatorios al prospecto quedan fuera de este incremento.
