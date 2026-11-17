# Segundo incremento: identificación y gestión de prospectos

Estado al 6 de noviembre de 2026: segundo incremento implementado y validado. Pasaron las pruebas automatizadas y el recorrido con Haiku real. Telegram aceptó el mensaje de prueba y Guillermo confirmó su recepción. Guillermo confirmó que todas las pruebas manuales fueron exitosas. Las mejoras del primer incremento siguen pendientes para otra etapa.

La [guía de pruebas del segundo incremento](../testing/segundo-incremento.md) registra la validación manual completada.

## Captura e identidad

- Explorar propiedades no requiere identificación.
- Al expresar interés en una propiedad o pedir visita, contacto humano o seguimiento, Maia solicita el celular amigablemente.
- El prospecto puede continuar en el website. Migrar a WhatsApp es opcional cuando integremos ese canal.
- El celular es el único dato obligatorio para crear la ficha del prospecto. El nombre es opcional.
- Maia confirma que el número quedó bien escrito. El piloto no envía códigos de verificación.
- Un número declarado no demuestra identidad ni permite acceder a conversaciones anteriores.

Si pide atención humana pero rechaza dar su celular, puede seguir explorando en el website. La solicitud queda registrada y el asesor recibe el contexto disponible con la indicación «celular no proporcionado». Maia explica que necesita un número para que lo contacten por teléfono, sin insistir ni prometer ese contacto. No inventamos un número para completar la ficha.

## Ficha del prospecto

El CRM conserva celular, nombre disponible, conversaciones, requisitos expresados, propiedades de interés, asesor responsable, estado comercial, siguiente paso pendiente y control de pausa de Maia.

Maia aprovecha lo expresado en la conversación. El asesor puede corregir requisitos y siguiente paso desde el CRM.

## Asignación

- Con propiedad elegida: asesor responsable de esa propiedad.
- Sin propiedad elegida: asesor predeterminado configurado en el CRM.
- Con propiedades de distintos asesores: un responsable inicial, el de la primera propiedad.
- El responsable puede cambiarse desde el CRM.

## Estados comerciales

| Estado | Significado |
| --- | --- |
| Nuevo | Registramos celular e interés; el asesor aún no confirma atención. |
| En atención | El asesor confirma desde el CRM que atiende al prospecto. |
| Sin interés | El asesor registra que el prospecto ya no desea continuar. |

Asignar al asesor o enviar Telegram no cambia el estado a En atención. Dejar de responder no cambia el estado a Sin interés. Cita agendada se añadirá con el incremento de citas.

## Control humano

El asesor puede contactar por el medio que prefiera y registra el avance en el CRM.

Pausar atención automática es un control independiente del estado comercial. Pasar a En atención no pausa a Maia. Al activar la pausa, Maia deja de responder y de enviar seguimientos; los mensajes entrantes siguen guardándose. El asesor puede reactivarla desde el CRM.

## Telegram

Cada asesor recibe sus avisos en una conversación privada de Telegram, configurada desde el CRM.

Motivos aceptados:

1. Nuevo prospecto asignado al asesor.
2. Petición de hablar con una persona.
3. Mensaje recibido mientras Maia está pausada.
4. Nuevo interés de un contacto que regresa, sin avisar por cada mensaje ordinario.

Cada aviso incluye motivo, resumen breve, celular, propiedad de interés y enlace al CRM. Si falta un dato, lo indica. El evento queda registrado en el CRM aunque Telegram falle. Reintentar un mismo envío no debe duplicar el aviso.

## Contactos que regresan

- Una ficha por celular normalizado, incluido el código de país.
- Una nueva conversación con ese número se asocia internamente como contacto con número declarado, sin identidad verificada.
- Conservamos asesor responsable y datos anteriores. La conversación nueva no sobrescribe automáticamente requisitos ni estado comercial.
- Cada conversación del website conserva su aislamiento. Declarar el mismo número no habilita acceso a otros historiales.
- El asesor recibe un aviso si existe nuevo interés.

## Fuera de este incremento

Google Calendar y citas, ciclo de seguimiento de 28 días, acompañamiento posterior a la intención de compra o renta, captación de propiedades e integración de WhatsApp. Los controles aceptados se conservarán al incorporar esos procesos.
