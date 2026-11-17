# Google Places y Maps en la captación del incremento 6

Decisiones de producto confirmadas por Guillermo el 15 de noviembre de 2026. Integración implementada y migración `0012_google_location_cache` aplicada. Activación de Google y validación con sus APIs reales pendientes de claves. [ADR de elección y conservación](../adr/0001-google-ubicacion-beta-rc.md), [investigación y fuentes](../research/autocompletado-direcciones-2026-11-15.md), [activación y límites reales](../testing/google-ubicacion-beta.md).

## Alcance confirmado

- Google Places para sugerencias de dirección y componentes disponibles; Google Maps para captación y fichas que presenten su contenido durante BETA y RC.
- Español y México; preferencia por Guadalajara/ZMG sin excluir otros estados.
- Al elegir una dirección se completan los campos disponibles, se centra/acerca el mapa y el propietario puede corregirlos. No inventar datos ni presentar un pin inicial como dirección encontrada.
- Mantener captura manual. Para terreno o rancho sin dirección convencional admitir estado, municipio, referencia escrita y punto, con revisión del equipo.
- Ocultar latitud y longitud del recorrido normal. Mantener dirección y punto exactos privados y la autorización independiente del equipo para publicación.
- Permitir consultas mínimas al proveedor, con información al propietario; no enviar nombre, email, teléfono ni contrato.
- Presupuesto inicial de $10 USD/mes, controles de consumo y alternativa manual al agotar disponibilidad. Una alerta de Google no corta el gasto.
- Separar datos comerciales de resultados Google temporales; actualizar estos últimos antes de 30 días sin cambiar contrato ni revisión comercial.

## Trabajo de implementación

1. **Datos y retención.** Diseñar un registro técnico separado con identificador Google, procedencia, fecha y caducidad. Inventariar/excluir copias de resultados temporales en captación, propiedad, acuerdos, adjuntos, conversaciones y almacenamiento del navegador. El contrato conserva los datos comerciales cuya procedencia permita ese uso; no una copia indiscriminada de la respuesta del proveedor.
2. **Consulta autorizada.** Añadir transporte en `backend/api` y un módulo pequeño de integración conforme a `docs/architecture/code-structure.md`. Validar país/tipos/campos, limitar solicitudes, agrupar sesiones correctamente y evitar consultas privadas en logs. Las claves del servidor no se entregan al navegador.
3. **Captación.** Implementar sugerencias accesibles, espera entre pulsaciones, cancelación y rechazo de respuestas tardías. Mapear municipio/localidad/colonia explícitamente. Separar dirección declarada, selección del proveedor y corrección; no sobrescribir campos manuales de manera silenciosa.
4. **Mapa.** Sustituir el visor correspondiente por Google Maps. El mapa inicial no tiene marcador seleccionado. Una selección válida acerca al inmueble; el mapa se puede corregir. No enviar al navegador público el punto ni el identificador privados para después ocultarlos visualmente.
5. **Alternativa manual.** Ajustar esquema y mensajes para ubicación no convencional. Conservar controles y datos propios existentes. Ante fallo externo o cuota agotada, permitir continuar con la alternativa aprobada.
6. **Actualización técnica.** Definir expiración, actualización y eliminación de resultados temporales también en copias y restauraciones. El worker de avisos no debe invalidar una aprobación solo por refrescar metadatos Google.
7. **Configuración.** Preparar instrucciones de proyecto Google Cloud con facturación habilitada, Maps JavaScript API y Places API (New), y Geocoding API solo si la estrategia elegida la necesita. Usar claves separadas/restringidas para navegador y servidor, dominios autorizados de BETA/local y límites por API. No activar servicios ni crear credenciales como efecto secundario de leer esta guía.

## Pruebas de aceptación

- Escribir dirección, navegar sugerencias con teclado y seleccionar en escritorio y móvil. Revisar autollenado por campo y zoom.
- Casos en Guadalajara, Zapopan y otros municipios; mismo nombre de calle en otra ciudad; fuera de Jalisco; colonia/número ausentes; terreno o rancho sin dirección convencional.
- Respuesta incompleta, sin coincidencias, red caída, agotamiento de cuota y consulta tardía tras cambiar dirección. Mantener los datos corregidos y la alternativa manual.
- Guardar y reanudar después de verificar cuenta; mantener autorización y privacidad entre propietarios.
- Refrescar un resultado vencido sin modificar contrato, revisión ni corrección humana. Rechazar uso de caché vencida y comprobar que no queda en acuerdos, adjuntos, conversaciones, navegador o restauraciones.
- Verificar que la ficha pública y su tráfico de red no contienen punto, dirección ni identificador privados salvo el permiso de publicación aplicable.
- Medir llamadas reales, SKUs y mapas abiertos. La previsión de 1,000 formularios no es una cuota de 1,000 solicitudes.
- Regresión de captación, exclusividad, publicación, tipos y compilación. La prueba con Google requiere proyecto, credenciales y muestra autorizada; pruebas simuladas no acreditan calidad real.

## Detalles que todavía no se dan por resueltos

- La conservación de una corrección manual del pin cuando se originó en el mapa Google. No basta afirmar que una confirmación cambia su licencia. Resolver sin actualizarla silenciosamente a una ubicación distinta.
- Procedencia y permisos de cada componente administrativo que se conserve o publique. La excepción para dirección del usuario no cubre automáticamente toda la respuesta de Places.
- Región pública aproximada: separar lo que declara el propietario de lo que devuelve Google y comprobar el uso permitido; nunca exponer el identificador exacto para dibujar una aproximación.
- Criterios cuantitativos de cobertura y precisión, y configuración real del proyecto Google Cloud.

La implementación adopta una vigencia conservadora de 29 días también para el punto ajustado sobre el mapa. No lo actualiza al punto original: vencido, pide confirmación de nuevo mediante el flujo correspondiente. Coordenadas propias de GPS/documentación tienen una alternativa avanzada independiente. No se declara conservación indefinida del ajuste ni una autorización jurídica general de todos los campos inferidos. La zona pública se resuelve por separado, sin punto ni identificador privados en sus respuestas.

Código implementado: `datalayer/google_locations.py`, `api/location.py`, tres modelos técnicos de sesión/caché/cuota, tarea horaria de mantenimiento y componentes compartidos `LocationFields` y `LocationMap` para website/CRM. La configuración usa el asistente `scripts/setup-google-maps-beta.sh` y un archivo Compose opcional, sin modificar la configuración principal. La correspondencia local y los permisos del contrato Google se deben validar con las condiciones efectivamente contratadas; las pruebas simuladas no acreditan precisión en Guadalajara.
