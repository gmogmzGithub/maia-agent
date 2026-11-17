# Avisos de errores y ubicación

Fecha: 2026-11-16.

## Comportamiento

- Website y CRM presentan los errores actuales mediante el mismo diálogo, sin cierre automático.
- La validación de campos agrupa los pendientes, permite seleccionar un campo y lo enfoca al cerrar. Los campos conservan el mensaje y el contorno de error hasta corregirse.
- La casilla de aprobación fuera de zona tiene acceso directo desde su error del servidor.
- Los éxitos, las instrucciones, la ausencia de sugerencias y los estados históricos de entrega no abren diálogos.
- Los reintentos requieren acción humana y una función explícita de la pantalla. Las cargas usan la cola idempotente existente; las lecturas se pueden repetir. Ningún diálogo reenvía contratos, aprueba ni publica por su cuenta.
- Ubicación ocupa toda la fila en el formulario de corrección del CRM; campos interiores en dos columnas o una según el ancho.

## Verificación en navegador

1. Registro vacío: una ventana con Email, Teléfono y Contraseña. Al repetir no duplica los mensajes.
2. Ir al campo enfoca Email; seleccionar Teléfono en la lista enfoca ese control. Tres campos con `aria-invalid` y tres mensajes junto a los controles.
3. Vista de 390 × 844: ventana entre x=18 y x=372, sin desbordamiento horizontal.
4. Ficha pública inexistente `/propiedades/0`: aviso del servidor con Entendido y Reintentar. Reintentar realiza otra consulta y permite presentar el mismo error de nuevo.
5. CRM, solicitud fuera de zona: marcar únicamente verificación de representación e intentar aprobar sin autorizar zona presenta el error del servidor en el diálogo. Ir al campo enfoca `outside`, marcado inválido. La aprobación falla y la solicitud conserva En revisión. La casilla de representación se devuelve a su estado inicial.
6. Abrir Corregir información: sección de ubicación de 862 px dentro de un grid de 862 px, `grid-column: 1 / -1`. Edición cancelada sin guardar.

Evidencia local: `/tmp/maia-errors/errores-movil.jpg`, `/tmp/maia-errors/error-zona.jpg`, `/tmp/maia-errors/ubicacion-crm.jpg`.

Pendiente de aceptación física: repetir en Safari/iPhone. La emulación de ancho no sustituye la prueba del dispositivo.
