---
status: accepted
---

# Google para ubicación durante BETA y RC

Guillermo eligió Google para las sugerencias de direcciones, autollenado y ubicación del inmueble durante BETA y RC. Se acepta la consulta de direcciones al proveedor con información al usuario, datos mínimos, captura manual de respaldo y presupuesto inicial de $10 USD/mes. Se prioriza esta integración frente a comparar primero Geoapify y LocationIQ; la cobertura precisa de Guadalajara todavía no se ha medido.

Guillermo confirmó también sustituir el mapa de captación y las fichas que muestren resultados Google por Google Maps. La elección no autoriza asumir almacenamiento indefinido; antes de implementar se debe cerrar cómo se conservarán los datos conforme al producto Google contratado. Una dirección sugerida y confirmada no se vuelve automáticamente independiente de las condiciones del proveedor. La dirección y coordenadas exactas siguen privadas por defecto.

Las cuotas se calculan por SKU y solicitudes reales, incluidas búsquedas abandonadas. La expectativa de menos de «1,000 créditos mensuales» no constituye una cuota técnica definida. Las alertas de presupuesto no cortan el gasto; la implementación requerirá límites de solicitudes y alternativa manual. [Investigación, precios y términos](../research/autocompletado-direcciones-2026-11-15.md).

Guillermo aceptó separar los datos comerciales duraderos de los resultados temporales de Google, con actualización de coordenadas antes de 30 días sin modificar el contrato aceptado. Los resultados temporales no deben copiarse a snapshots ni historial permanente. Queda por concretar el tratamiento de la corrección manual del punto: la actualización técnica no puede desplazarla silenciosamente ni se asume permiso de conservación ilimitada por el solo hecho de confirmarla. Ver [plan de integración](../design/google-ubicacion-incremento-6.md).
