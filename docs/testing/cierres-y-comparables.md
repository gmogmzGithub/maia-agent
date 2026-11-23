# Registro de cierres: implementación y validación

## Corrección vigente: sesión y autoría · 22 de noviembre de 2026

Guillermo elimina el permiso adicional de cierres, también para administradores. Una cuenta activa del equipo con sesión CRM puede registrar y actualizar operaciones. Se retiran los controles de permisos y su endpoint; las antiguas tablas de autorización se conservan únicamente como datos históricos, sin condicionar acciones. Se mantiene la autenticación del equipo, CSRF, revisión del resumen y control de concurrencia.

Cada nueva revisión de operación y evento de propiedad/captación, además de las vinculaciones de inmuebles, conserva el identificador y una copia del correo del autor obtenidos de la sesión en el servidor. Un correo enviado por el cliente no decide la autoría. Cambiar después el correo de la cuenta no reescribe el historial. Los eventos previos conservan su identificador; no se inventa el correo que tenían entonces. La migración 0017 añade esos campos sin cambiar los datos anteriores. Esta decisión sustituye los requisitos anteriores de habilitación adicional.

22 de noviembre de 2026. Alcance: acuerdos Q1–Q39 del [diseño funcional](../design/cierres-y-comparables.md) y su [modelo técnico](../design/cierres-modelo-tecnico.md). Implementación local; la aceptación comercial del producto corresponde a Guillermo.

## Recorrido disponible

Corrección de Guillermo: no hay pestaña Cierres. Desde Propiedades o la captación vinculada, el asesor marca vendida/rentada y añade precio final y fecha reales. Dirección, zona, superficies y características provienen de la ficha de origen; los faltantes se corrigen allí. Retirar o cancelar conserva datos y acuerdos sin crear una operación. Operaciones anteriores queda como carga excepcional de históricos. El equipo prepara borradores; su autor o un administrador puede editarlos/eliminarlos mientras nunca hayan sido confirmados. Un administrador habilita explícitamente a los usuarios que pueden confirmar y realizar cambios posteriores desde **Permisos de cierres**. No se concedió ese permiso automáticamente a cuentas existentes.

El vendedor revisa y completa zona, dirección exacta y superficies en el alta o edición de origen, sin repetirlas al registrar el resultado. Google ofrece el mismo apoyo de captura y mapa que en captación, con alternativa manual. Confirmar exige resumen revisado, datos obligatorios y revisión de posibles duplicados. Los resultados temporales del mapa no entran al histórico.

Una operación actual termina únicamente la oferta vinculada y sus acuerdos abiertos. Los históricos no cambian ofertas ni búsquedas actuales. Las citas se conservan y se generan avisos internos al asesor; no se generan respuestas WhatsApp de citas al confirmar el cierre.

La ficha muestra precio final y moneda, fecha, zona, superficies separadas, cargos, características desconocidas e historial. Una corrección conserva el original. Anular significa que la operación nunca ocurrió; revertir significa que ocurrió y después se deshizo. Solo una oferta con cierre anulado por error admite reapertura expresa. Esa reapertura conserva el cierre y los acuerdos terminados, mantiene la oferta despublicada y abre otro periodo para un cierre nuevo.

La vinculación de identidades es humana y requiere motivo. Relaciona sus operaciones conservando identificadores y revisiones originales; no fusiona ni verifica direcciones automáticamente. La búsqueda del comprador puede marcarse como atendida mediante una acción separada que identifica la intención concreta y conserva el permiso general de contacto.

## Evidencia automatizada

- Suite completa del backend tras eliminar el permiso adicional y conservar el correo de sesión: **306 correctas, 2 opcionales omitidas**.
- Registro de cierres: **17 pruebas**, incluidas permisos, concurrencia, migración de datos, identidad compartida, borradores, históricos, reapertura y privacidad.
- Suite existente del frontend: **59 correctas**.
- Verificación de tipos, compilación, análisis estático y comprobación de modelos/migraciones: correctos. La alerta de seguridad que apareció durante la implementación inicial quedó resuelta el 22 de noviembre mediante la [actualización a Next.js 16.4.6](next-seguridad-2026-11-22.md).
- Proxy real del website: creación y lectura de conversación correctas, sin redirección del POST, tanto en aceptación aislada como en el acceso local habitual después de actualizar los servicios.

Las pruebas se ejecutan con el entorno Python existente del backend y Node disponible para los comandos del frontend. La implementación inicial no cambió dependencias; la actualización posterior modifica Next.js y sus paquetes asociados, con React y React DOM conservados.

`backend/tests/test_closings.py` demuestra:

| Acuerdos | Casos comprobados |
| --- | --- |
| Q1–Q8 | Registro separado, renta y venta de un inmueble, permiso explícito, responsable distinto del usuario, revisiones inmutables. |
| Q9–Q12 | Precio base, monedas y cargos separados; fecha parcial como borrador; características desconocidas sin valores inventados. |
| Q13–Q16 | Efectos limitados a la oferta, fin de acuerdo conservando su copia, anulación, vinculación humana de identidades y advertencias de duplicados. |
| Q17–Q24 | Dirección urbana/rural suficiente, comprador opcional, acceso interno, marca de prueba y resolución acotada de búsqueda. |
| Q25–Q32 | Notas opcionales, solo precios finales, reversión, borrado de borradores, permisos de preparación y corrección con historial. |
| Q33–Q38 | Fechas válidas, superficies de terreno/construcción/privativa, resumen vigente, conflictos concurrentes y rechazo de campos temporales Google en el contrato de cierre. La integración compartida de ubicación también tiene sus pruebas existentes. |
| Q39 | Anular no republica, reapertura autorizada/idempotente, periodo nuevo, cierre posterior independiente y acuerdos que no reviven. |

Las acciones de mutación comprueban revisión y permiso al ejecutarse. Una solicitud repetida devuelve el resultado comprometido; una clave reutilizada con otros datos se rechaza. La confirmación concurrente de la misma oferta deja un solo cierre por periodo.

## Validación de la corrección de flujo

Actualización de autoría: 24 pruebas de cierres y resultados correctas. Una cuenta del equipo sin autorización adicional confirma por API; un correo falsificado en la solicitud se ignora, el historial conserva el correo de sesión incluso después de cambiar el correo del usuario, y una cuenta externa o sin sesión continúa sin acceso. La aceptación en navegador se repitió con una cuenta del equipo que no es administradora, sin conceder permisos, y comprobó el correo persistido. Compilación y análisis estático correctos. La migración 0017 se aplicó localmente sin modificar los datos previos comprobados.

Backend, worker y web se reconstruyeron y actualizaron con este ajuste; los tres servicios quedaron saludables. Inicio, CRM, propietarios, salud e inventario público respondieron 200. La ruta privada de resultado sin sesión mantuvo 403 y `private, no-store`; creación y lectura de conversación por el proxy correctas. Los servidores y la base de aceptación se eliminaron al terminar.

Seis casos de `tests/test_property_outcomes.py` cubren herencia desde alta interna y captación, precio solicitado separado, retirada sin cierre, restauración a revisión, rechazo de fuente obsoleta y cancelación de contrato conservando sus datos y copia aceptada. Las nuevas copias excluyen referencias temporales Google.

En navegador con API/base reales aisladas: alta interna con dirección Google simulada, cierre desde la propiedad con solo precio/fecha finales, copia exacta de dirección y superficies, conservación del precio anunciado y retirada de otra propiedad sin operación. Vista móvil de 390 px sin desbordamiento. No se enviaron mensajes reales. La aceptación física de Guillermo sigue pendiente.

## Aceptación anterior en navegador

El siguiente recorrido corresponde a la versión anterior al ajuste de navegación. El recorrido vigente parte de la propiedad, según la sección anterior y la guía manual actualizada.


Se recorrió el CRM con sesión real, CSRF y backend real, usando una base PostgreSQL temporal y una cuenta de prueba:

1. Conceder explícitamente el permiso desde el CRM.
2. Abrir el formulario desde una oferta mediante enlace directo.
3. Seleccionar dirección con el componente Google compartido y revisar calle, números y superficies.
4. Guardar borrador con marca de prueba y características desconocidas.
5. Revisar y confirmar, conservando exactamente centavos en el precio final.
6. Recargar la ficha y cambiar entre vistas de escritorio y móvil sin perder el registro seleccionado ni desbordar horizontalmente.
7. Corregir el precio, comprobar la revisión nueva y conservar el importe original.
8. Anular y reabrir expresamente, conservando la oferta despublicada.

El proveedor Google y el dibujo del mapa se simularon en el navegador para evitar consultas facturables. El resto del recorrido utilizó los componentes, API y base de datos reales. Las pruebas no acreditan cobertura geográfica de Google ni sustituyen una prueba física de Safari/iPhone. No se reactivó el piloto personal ni se enviaron mensajes reales.

La selección de borradores, confirmaciones y correcciones actualiza un enlace `?closing=...` que restaura la ficha al recargar. En móvil, la ficha seleccionada aparece antes de la lista; las acciones de alta ocupan el ancho disponible.

## Migraciones locales

Se aplicaron `0014_closing_registry`, `0015_physical_property_link` y `0016_property_source_and_retention` a la base local. Se compararon huellas de los campos previos antes/después: claves y referencias, precios solicitados, publicación, fechas de inventario, datos/estados/revisiones de captación, copias aceptadas de acuerdos y estados/permisos de seguimiento se conservaron. La última migración tampoco modificó cierres ni autorizaciones existentes; agregó datos de origen y eventos de línea base sin inventar operaciones.

La migración crea una identidad provisional por oferta existente y una intención por ciclo, sin unir inmuebles por dirección ni atribuir requisitos actuales a búsquedas históricas. No inventa cierres, precios finales, permisos ni fechas. Las ofertas nuevas reciben identidad física al crearse. Las relaciones históricas se agrupan después por decisión humana.

El nuevo registro usa el mismo identificador Django `core`, la base y la cola existentes. Las direcciones privadas y los precios finales no se añadieron a `Property.details`, a las proyecciones públicas ni a la cuenta del propietario. La marca de prueba clasifica datos; no simula las acciones del producto.

## Servicios locales

Se reconstruyeron y actualizaron backend, worker y web del proyecto local existente, conservando sus archivos de configuración Google/Resend y los volúmenes. Los tres servicios quedaron saludables; la base existente no se recreó.

Después de la corrección de flujo se repitió la actualización de los tres servicios, con `0016` aplicada y Next.js 16.4.6 comprobado dentro del servicio web. Inicio, CRM, propietarios, salud e inventario público respondieron 200; el resultado privado sin sesión respondió 403 con `private, no-store`. El proxy volvió a crear y recuperar una conversación correctamente. La base de aceptación aislada se eliminó después de detener sus servidores.

El acceso habitual del CRM carga el módulo nuevo. Una petición anónima al registro responde HTTP 403 con `Cache-Control: private, no-store`. La creación/lectura de conversación por el proxy habitual devuelve HTTP 200. Los servidores y la base temporales usados para aceptación se detuvieron y eliminaron al finalizar.

No se hicieron commits ni pushes como parte de esta implementación.

## Fuera de esta entrega

Comparador, valoración automática, fuentes externas, historial de precios anunciados y algoritmos de verificación de datos. Continúan separados los pendientes previos de credencial para operación continua y textos con Santiago. La actualización de seguridad de Next.js ya se completó.

Guillermo cerró la aceptación manual de este recorrido el 22 de noviembre de 2026, tras reportar que las pruebas restantes salieron bien. El [recorrido por etapas](cierres-recorrido-guillermo.md) queda para futuras regresiones. Esto no declara preparación para RC ni verificación de todos los dispositivos.

## Resultados manuales reportados por Guillermo · 22 de noviembre

- Confirmó que el flujo funciona tras eliminar el permiso adicional.
- Comprobó que la ficha se conserva después de despublicar.
- Registró una renta y probó desde su teléfono; reportó que todo salió bien. No especificó navegador ni modelo del dispositivo.
- Corrigió el precio final y verificó en el historial ambos importes, su correo y la fecha, sin problemas reportados.

- Tras solicitar las pruebas restantes de cierre desde captación externa y retirada por cancelación, Guillermo respondió «Done! All good!» y pidió cerrar estas pruebas. Se registra su aceptación de ambas, sin atribuir comprobaciones adicionales no reportadas.
