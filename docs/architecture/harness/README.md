# Mapas del harness de Maia

Instantáneas del diseño: «Actual» representa el código antes del rediseño; «Propuesta» representa el diseño acordado. No son una inspección dinámica de los servicios. El [documento de estructura](../code-structure.md) y el [plan técnico](../../design/plan-harness-conversacional.md) registran el estado de implementación posterior.

Abrir [el visor](index.html) en un navegador o visitar `http://localhost:8766/` mientras esté activo el servidor local de diagramas. El visor tiene tres pestañas:

1. [Arquitectura actual](actual.html): responsabilidades observadas en el código.
2. [Rediseño acordado](propuesta.html): propuesta final, validación, presentación y continuidad, implementado posteriormente; consultar el mapa actual de código.
3. [Memoria](memoria.html): relación entre PostgreSQL, procedimientos, contexto temporal y continuidad propuesta.

Cada HTML del mapa es independiente y funciona sin bibliotecas remotas. El visor `index.html` requiere los tres archivos a su lado. Los controles fijos de los mapas están en inglés; el contenido está en español.

La estructura implementada está en el [mapa de bloques y archivos](code-map.md).

## Alcance lógico

- `harness/runtime.py` coordina contexto, llamadas y herramientas. No toda la plataforma pertenece al harness.
- `agent` contiene instrucciones y catálogo de herramientas.
- `datalayer` implementa acceso autorizado y operaciones del negocio.
- `worker` programa y ejecuta trabajos; PostgreSQL conserva datos.
- Los bloques dibujados no representan microservicios, bases adicionales ni una topología AWS.
- Las flechas resumen relaciones; no enumeran todas las llamadas o transacciones. La flecha del agente a herramientas resume solicitud y retorno del resultado.
- El mapa general separa el recorrido de salida del detalle de lectura de memoria, mostrado en el tercer mapa.
- La publicación agrupa persistencia y transporte como responsabilidad lógica, pero no garantiza lectura del cliente. La continuidad efectiva depende del estado observable del canal.

Seguimiento, Telegram y sincronización de Google Calendar mantienen sus módulos existentes. El rediseño del turno no cambia automáticamente la selección de plantillas del seguimiento. RAG, vectores, SQLite, almacenamiento frío y nuevas barreras de contenido no se declaran implementados ni necesarios por estos diagramas.

## Evidencia y decisiones

- [Organización implementada](../../architecture/code-structure.md).
- [Comportamiento acordado](../../design/harness-conversacional.md).
- [Plan técnico](../../design/plan-harness-conversacional.md).
- [Comparación con Hermes y Waku](../../research/contexto-memoria-hermes-waku-2026-10-24.md).

Las especificaciones editables son `*.architecture.json`. Se generaron con la skill `archify` instalada. Cada entrega pasó 9/9 comprobaciones de composición, sin errores ni avisos. Las verificaciones de navegador se registran por separado en `*.visual-check.json`, vinculadas al hash del HTML inspeccionado. La revisión perceptual se registra en `validacion.md`.

El servidor local temporal está aislado de los contenedores de la aplicación. Para detenerlo:

```sh
docker stop maia-harness-diagrams
```

Para volver a iniciarlo desde `/Users/el-men/Workspace/maia-agent`:

```sh
docker run -d --rm --name maia-harness-diagrams \
  -p 127.0.0.1:8766:8000 \
  -v "$PWD/docs/architecture/harness:/diagrams:ro" \
  -w /diagrams --entrypoint python maia-incremento1-backend \
  -m http.server 8000 --bind 0.0.0.0
```

La imagen del backend debe existir. Si el nombre del contenedor ya está en uso, no repetir el arranque.
