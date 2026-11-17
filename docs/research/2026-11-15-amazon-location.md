# Amazon Location para direcciones de captación

Investigación del 15 de noviembre de 2026. Propuesta, sin integración ni alta de servicios. No se enviaron direcciones de propietarios a ningún geocodificador.

## Encaje

Amazon Location separa `Autocomplete`, que propone direcciones sin coordenadas, y `GetPlace`, que recupera dirección y posición de la selección. La primera llamada puede devolver solo etiqueta e identificador; pedir componentes adicionales durante cada pulsación cambia el nivel facturable. Para Maia interesa sugerir con Label y consultar el detalle únicamente al seleccionar. [Autocomplete](https://docs.aws.amazon.com/location/latest/developerguide/autocomplete.html), [GetPlace](https://docs.aws.amazon.com/location/latest/developerguide/get-place.html).

Las sugerencias son temporales. Para conservar el resultado elegido en el inventario debe solicitarse `GetPlace` con `IntendedUse: Storage`. La documentación de precios llama al nivel **Stored**, pero el valor del parámetro es **Storage**. La documentación contiene una mención inconsistente a `Stored` como valor; la referencia de API/CLI enumera `SingleUse | Storage`. [Uso previsto](https://docs.aws.amazon.com/location/latest/developerguide/places-intended-use.html), [niveles de precio](https://docs.aws.amazon.com/location/latest/developerguide/places-pricing.html), [referencia GetPlace](https://docs.aws.amazon.com/cli/latest/reference/geo-places/get-place.html).

La guía permite almacenamiento indefinido bajo el nivel Stored. Los términos permiten guardar geocodificaciones cuando se declara ese uso y exigen atribución; no equivalen a autorización para revender una base geográfica ni eliminan otras restricciones. Antes de contratar hay que confirmar el encaje de los campos de GetPlace y su exposición en fichas públicas con el proveedor de datos concreto. No se encontró una prohibición general de mapas externos equivalente a la cláusula de Mapbox; esa ausencia no se interpreta como permiso contractual universal. [Términos §82](https://aws.amazon.com/service-terms/).

## Coste reproducible

Tarifa consultada para **US East (N. Virginia)**, USD sin impuestos. Se descargó el catálogo público oficial de AWS y se filtraron `operation=Autocomplete`, `type=Autocomplete request (Label)` y `operation=GetPlace`, `type=GetPlace request (Stored)`. El catálogo indica publicación `2026-09-11T12:44:49Z`.

| Operación | Precio por llamada | Por 1,000 |
|---|---:|---:|
| Autocomplete Label | $0.0002 | $0.20 |
| GetPlace Stored | $0.004 | $4.00 |

Fuentes: [catálogo oficial regional JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonLocationService/current/us-east-1/index.json), [página de precios](https://aws.amazon.com/location/pricing/).

Hipótesis para comparar: ocho consultas de sugerencias y una selección por trámite. `Coste = N × (8 × 0.0002 + 0.004)`. No incluye mapas, servidor, transferencia, impuestos, consultas inversas, abandonos ni cambios adicionales de selección. N representa trámites de búsqueda con esa actividad, no garantiza equivalencia con propiedades finalmente publicadas.

| Trámites/mes | Sugerencias | Detalles almacenables | Coste de referencia sin promociones |
|---:|---:|---:|---:|
| 100 | 800 | 100 | $0.56 |
| 1,000 | 8,000 | 1,000 | $5.60 |
| 10,000 | 80,000 | 10,000 | $56.00 |

El free tier publicado incluye 10,000 sugerencias Label y 20,000 consultas Core mensuales por tres meses. **Core no cubre el detalle Stored de esta propuesta**. Existen además créditos para clientes nuevos sujetos a elegibilidad y vigencia; no se descuentan en la tabla. [Free tier](https://aws.amazon.com/location/pricing/).

## Cobertura y límites de la evidencia

La tabla oficial incluye México, pero varios indicadores de calidad aparecen como elementos visuales en la página y no se recuperaron como texto. No se asigna una categoría de calidad a México a partir de celdas vacías. La cobertura declarada no acredita número exterior, colonia correcta ni precisión del acceso en Guadalajara. [Cobertura](https://docs.aws.amazon.com/location/latest/developerguide/data-quality.html).

No debe confundirse búsqueda de direcciones con el producto separado **Address Validation**: la cobertura publicada de este último enumera Australia, Canadá, Reino Unido y Estados Unidos, no México. No se recomienda facturar una validación postal mexicana que esa tabla no acredita. [Cobertura de Address Validation](https://docs.aws.amazon.com/location/latest/developerguide/data-quality.html).

El proveedor puede recibir las consultas fuera de la región AWS de la solicitud. AWS recomienda evaluar exactitud para el uso concreto. La tabla regional de precios no prueba residencia de los datos en México. [Términos §82.1–82.2](https://aws.amazon.com/service-terms/).

## Recomendación provisional

Candidato económico para un piloto comparativo si interesa evitar una suscripción mínima y contratar explícitamente almacenamiento. Compararlo con Geoapify y LocationIQ sobre un conjunto acordado de direcciones mexicanas; no elegirlo solo por precio. Conservar confirmación humana del punto, campos editables y captura manual para inmuebles rurales o no localizados. Ninguna cuenta AWS, clave ni prueba con domicilios reales se creó durante esta investigación.
