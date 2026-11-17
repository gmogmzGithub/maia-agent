# Validación de los mapas

Fecha: 7 de noviembre de 2026. Tipo de los tres diagramas: `architecture`.

## Entrega determinística

Los tres HTML pasaron `deliver` con 9/9 comprobaciones `showcase`, cero errores y cero avisos. Esta comprobación no acredita comportamiento de la aplicación Maia.

| Mapa | Especificación, bytes | HTML, bytes |
| --- | ---: | ---: |
| Propuesta | 5955 | 717368 |
| Actual | 5539 | 716682 |
| Memoria | 3244 | 707852 |

SHA-256 de especificación y artefacto, respectivamente:

```text
propuesta.architecture.json
455875bb4dc49a03f1fe13eccdaade149aed7fe77a70a2a3576846120168838a
propuesta.html
d63e68bed85cc75570c97b6c81d6991cb3b4620a5f2790522725400948bca0de

actual.architecture.json
4bc4f0a714e8ccd32253dfe2621bb85132a85d01ce8fb2addb4fed835124b63f
actual.html
5d5cc0f5d264c3af0ecf56af2f2c211a7d0f1a8cd370a813042ddacb26fb985f

memoria.architecture.json
ee3071b5a40ae3debda54e357df4b0aa702b48fac121095b9eba42ddfbf5136e
memoria.html
477f7be5fa69d30bfb82fe6c59a2666e94221c247a8b60cc3a37beab50f3cbbf
```

## Navegador automatizado

`browser_evidence: passed` para los tres artefactos finales. Se usó el comando `visual-check` de la skill en un contenedor temporal con Chromium instalado desde el registro de Alpine. Ese contenedor terminó; no modificó los servicios de Maia.

Contención, legibilidad y controles comprobados en 1440×900, 1600×1000, 1920×1080 y 2048×1320. Ningún desbordamiento horizontal o vertical en los HTML independientes finales. Capturas claras y oscuras en los dos tamaños extremos.

Recibos vinculados a los hashes anteriores:

- [Propuesta](propuesta.visual-check.json).
- [Actual](actual.visual-check.json).
- [Memoria](memoria.visual-check.json).

## Revisión perceptual y navegación

`visual_review: passed`. Se inspeccionaron los tres mapas claros en el visor y las capturas oscuras finales; también la propuesta clara a 2048×1320. Se revisaron texto, direcciones y cruces. La inspección es visual, separada de la comprobación automatizada.

Se comprobaron las tres pestañas del visor, el cambio de apariencia y el enfoque «Recorrido del turno», con retorno al diagrama completo. El menú de exportación se abrió y muestra PNG, JPEG, WebP y SVG; no se verificaron archivos exportados. La fuente JSON permite editar y regenerar los mapas.

`correction_rounds: 1` de revisión de escritorio tras la primera entrega: se compactaron los espacios verticales y se retiraron tarjetas repetidas en la guía, manteniendo tipografía y nodos. Después se repitieron entrega y verificación sobre los artefactos finales.

El visor contenedor `index.html` se revisó manualmente en el navegador disponible. La matriz automatizada corresponde a los tres mapas independientes, no a todas las dimensiones del visor contenedor ni a móviles.

La arquitectura propuesta y la nueva continuidad siguen sin implementar. No se ejecutaron pruebas funcionales de Maia por este cambio documental.
