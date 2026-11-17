# Captación CRM: estados y navegación móvil

Cambio visual del incremento 6, 15 de noviembre de 2026. No modifica estados persistidos, permisos, revisión, aceptación, publicación ni correos.

## Comportamiento

- Entrada en «Por revisar». Pestañas con contadores calculados sobre las captaciones recibidas: Por revisar (`submitted`), En proceso (`approved`, `accepted`), Publicadas (`published`) y Todas. Las descartadas, retiradas y vencidas siguen accesibles en Todas. Se conserva el orden del servidor por actualización.
- Una revisión aprobada se etiqueta «Espera aceptación», azul, y explica que el propietario debe aceptar la exclusividad. Exclusividad aceptada se etiqueta «Lista para publicar», morado. «En revisión» usa ámbar y «Publicada», verde. Las etiquetas incluyen texto e icono; los estados cerrados son grises. La selección usa borde lateral oscuro y fondo blanco, independientemente del estado.
- El encabezado de Captación deja de mostrar los contadores del inventario general. «Solicitudes» muestra el total real de captaciones; no repite el título Captación.
- Escritorio conserva lista y detalle en columnas. Hasta 760 px, primero se muestra únicamente la lista, sin scroll interno. Abrir una tarjeta muestra únicamente su ficha. «Volver a solicitudes» conserva filtro, selección y posición de desplazamiento. La cabecera de la ficha permanece visible al bajar por sus datos e imágenes, con volver, nombre, estado y siguiente paso.
- En celular, la cabecera del CRM se compacta y ofrece «Ver sitio». Las cuatro pestañas de captación se distribuyen en dos filas; no exigen desplazamiento horizontal. El UUID queda disponible en «Referencia de solicitud», contraído por defecto.
- Un enlace de CRM con `capture` abre la ficha y el grupo correspondientes. Actualizar y las acciones existentes refrescan los contadores, conservando el filtro elegido. Las pestañas y la selección se bloquean mientras se procesa una acción para no cambiar de solicitud durante su respuesta.

## Estructura

`frontend/src/crm/lib/capture-status.ts` concentra agrupación, etiquetas y siguiente paso. `components/CaptureStatus.tsx` presenta la etiqueta compartida por tarjeta y ficha. `components/Captures.tsx` mantiene selección, filtro, apertura móvil y restauración del desplazamiento; `styles/captures.css` contiene los estilos del CRM. Las rutas y el backend no cambian.

## Validación

25 pruebas frontend aprobadas, incluidas las tres nuevas de agrupación, conservación del orden, distinción entre revisión aprobada/exclusividad aceptada/publicación y ruta de enlaces directos. TypeScript y compilación aprobados.

Comprobación real en Chrome del sandbox con las dos captaciones existentes: contadores 1 por revisar, 0 en proceso, 1 publicada y 2 totales; estado vacío de En proceso; filtro Todas con los dos estados distinguibles; selección y detalle de escritorio. Vista de 440 px: lista sin scroll interno, detalle separado, barra sticky a `top: 0` al desplazarse y regreso al mismo filtro/posición. También se comprobaron 390 px sin desbordamiento horizontal y un enlace directo a la propiedad publicada, que abrió su ficha en Publicadas. En 390×520 px se conservó el desplazamiento real de 234 px al regresar a Todas. La navegación de pestañas por teclado también se comprobó. No se aprobaron, publicaron ni editaron solicitudes durante la comprobación. Los estados de En proceso no estaban presentes en los datos del piloto; su clasificación y distinción se comprobaron con las pruebas de presentación.

Queda la aceptación visual en un iPhone físico/Safari y con títulos largos o suficientes solicitudes para varias pantallas. Evidencias locales en `/tmp/maia-capture-status/`.
