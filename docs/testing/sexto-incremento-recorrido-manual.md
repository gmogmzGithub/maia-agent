# Incremento 6: recorrido de aceptación manual

## Cierre de aceptación para BETA · 16 de noviembre de 2026

Guillermo confirmó que las pruebas 1–10 funcionan y, después de revisar las pruebas pendientes de renovación/retirada y recorrido móvil/tablet, confirmó también las 11–12: «Done! All good!». **Las 12 pruebas de este recorrido quedan aceptadas por Guillermo y el incremento 6 queda cerrado para BETA.**

La confirmación es de aceptación manual del usuario; no implica una nueva ejecución técnica de cada caso de la guía extendida ni aporta identificadores, dispositivos o capturas adicionales. Se conservan los resultados técnicos documentados en sus guías respectivas.

Permanecen fuera de este cierre el contrato definitivo, el rediseño completo de cuentas/verificación de celular y los requisitos de operación para producción. Este cierre no declara cerrados los pendientes de Meta del incremento 4 ni inicia el incremento 5.

## Recorrido aceptado

La tabla conserva los pasos y resultados esperados para futuras regresiones. Las modificaciones del 15 de noviembre incluyen Google y la eliminación del formulario «Habla con tu asesor».

| # | Qué hacer | Resultado esperado |
|---|---|---|
| 1 | Abrir liga del correo sin sesión, iniciar como propietario y aceptar contrato. | Abre la propiedad correcta; seis meses desde aceptación. |
| 2 | Actualizar CRM, publicar y repetir clic. | Una sola propiedad publicada, con fotos, precio, moneda y datos correctos. |
| 3 | Revisar Actividad y avisos. | Correo `delivered`, además de recibido. |
| 4 | Crear otra cuenta; probar verificación, reenvío, cierre y recuperación. | Correos/enlaces funcionan; no entra a Mis propiedades sin verificar; se conserva el avance durante acceso. |
| **5** | **Guardar borrador, cerrar sesión y retomarlo; intentar abrirlo desde otra cuenta. Añadir los casos de Google de la guía.** | **El propietario recupera los datos; otra cuenta no accede a solicitud, archivos, contrato ni punto privado.** |
| 6 | Arrastrar y seleccionar fotos; añadir durante la carga, reintentar fallos, portada/orden/giro; probar 4/5/20/21 y HEIC desde celular. | Optimiza y orienta bien; mínimo 5 y máximo 20 fotos. Selector y arrastre comparten cola. Reintentos sin duplicar; lote excedente identifica rechazadas. Planos y 360 opcionales. |
| 7 | Completar Venta, Renta y Preventa; revisar categorías residenciales, comerciales, industriales y rurales. | Campos/subtipos correctos; sin Temporada ni Departamento Compartido. |
| 8 | Aprobar fuera de zona base; publicar sin ubicación exacta y luego con permiso. | Exige aprobación de zona y respeta privacidad. Google aproxima por zona independiente. |
| 9 | Corregir solicitud aprobada/publicada desde Captación. | Nueva revisión y aceptación; no publica con contrato anterior. |
| 10 | Buscar MXN/USD con presupuesto; opinión de valor sin comunicar. | Respeta moneda y privacidad de opinión. |
| 11 | Coordinar renovación/retirada con el asesor por WhatsApp y ejecutarlas desde CRM. | Renovación pide otra aceptación; retirada despublica y conserva historial/citas. **Ya no hay formulario de solicitudes en la cuenta del propietario.** |
| 12 | Repetir recorrido en celular/tablet y visor de fotos CRM. | Sin pérdida de datos, superposiciones ni acciones inaccesibles. |

[Activar y probar Google](google-ubicacion-beta.md). Registrar por prueba cuenta/propiedad de prueba, fecha, dispositivo, resultado y evidencia; nunca claves ni enlaces de verificación privados.

[Detalle de arquitectura y comprobaciones de fotos por arrastre](captacion-fotos-arrastre.md).

[Estados y navegación móvil de Captación CRM](captacion-estados-crm.md): comprobar filtros, etiquetas, barra de estado y regreso a la lista en la prueba 12.
