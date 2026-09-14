# Plan de rediseño del sitio público

Estado: implementado y verificado localmente.

## Objetivo

Rediseñar la portada y el catálogo público de Larevia con una experiencia muy
cercana a la referencia visual: encabezado compacto, catálogo denso, tarjetas
claras, características fáciles de leer y un Buscador con IA que abre una
conversación con Maia sobre el contenido desenfocado.

La similitud se aplica a la estructura, densidad, jerarquía, ritmo visual y
comportamiento. Larevia conserva su identidad, español de México, tipografía,
colores, textos e iconografía propios.

## Principios que no cambian

- Product continúa siendo la autoridad de inventario, publicación, filtros,
  disponibilidad, guardadas y políticas.
- Hermes continúa siendo responsable de comprender lenguaje natural, aclarar
  ambigüedades, mantener la conversación y componer respuestas.
- El navegador nunca se conecta directamente con Hermes.
- El Buscador con IA sólo puede consultar Listings elegibles para `PUBLIC_SHARE`
  dentro de la Organización resuelta por el dominio público.
- Toda la interfaz, incluyendo ejemplos, errores, filtros y estados, usa español
  de México.
- No se muestran direcciones privadas, Listings no publicados ni datos
  inventados para completar una tarjeta.

## Alcance visual

### Encabezado público

El encabezado global de escritorio tendrá esta composición:

`Larevia | Comprar | Rentar | Zonas | [Buscador con IA] | Guardadas | Cuenta demo`

- `Filtros` aparece solamente en el catálogo, donde tiene una acción real.
- El Buscador con IA ocupa el centro y muestra ejemplos rotativos.
- `Guardadas` abre la colección real del navegador.
- El icono de persona abre una Cuenta demo exclusivamente visual.
- El acceso de administración se retirará del encabezado público en un cambio
  posterior.

En móvil habrá dos niveles:

1. Larevia, Guardadas, Cuenta demo y menú.
2. Buscador con IA a todo lo ancho y `Filtros` cuando corresponda.

### Cuenta demo

La Cuenta demo existe únicamente para representar el diseño futuro del área de
cuenta. No introduce lógica de cuenta.

- No crea identidad, usuario, Contact, correo, contraseña ni sesión autenticada.
- No guarda un perfil ni sincroniza datos entre dispositivos.
- No añade registro, inicio de sesión, cierre de sesión ni recuperación.
- Su panel debe estar marcado claramente como `Demo`.
- Puede enlazar a `Propiedades guardadas`, que ya es una función real.
- La futura cuenta podrá sustituir esta implementación sin cambiar la posición
  general del control.

### Portada

La portada deja de comenzar con una fotografía gigante. Su orden será:

1. Encabezado compacto.
2. Introducción breve de Larevia.
3. Selección de seis a ocho Listings públicas.
4. Exploración por zonas.
5. Explicación breve de cómo funciona.
6. Invitación para vender o rentar.
7. Pie de página.

Las secciones secundarias aparecen después del inventario, no antes.

### Catálogo

`/propiedades` será la superficie más cercana a la referencia:

- cuadrícula de tres columnas en escritorio amplio;
- dos columnas en tableta;
- una columna en móvil;
- márgenes contenidos, separadores finos y poca altura desperdiciada;
- vista de cuadrícula y vista de lista, ambas funcionales;
- `vista=cuadricula` o `vista=lista` en la URL;
- sin mapa en esta entrega.

## Tarjetas de Listing

Cada tarjeta puede mostrar:

- fotografía de portada o mosaico autorizado;
- operación y tipo de propiedad;
- precio correspondiente a la búsqueda activa;
- nombre corto de la Listing;
- Ubicación Pública;
- fila de características con iconos limpios;
- fuente o atribución pública cuando corresponda;
- antigüedad pública durante los primeros siete días;
- corazón para guardar.

Las características posibles incluyen recámaras, baños, estacionamientos,
superficie de construcción, superficie de terreno, antigüedad y niveles. Sólo se
renderizan valores conocidos; nunca se sustituyen con cero, guiones o estimaciones.

La portada usa una fotografía normalmente. En escritorio puede usar un mosaico
cuando existan suficientes fotografías aprobadas; en móvil siempre usa una sola
portada para conservar claridad y rendimiento.

El corazón tiene estado vacío o lleno, nombre accesible y confirmación visible.
La primera propiedad guardada conserva el requisito vigente de Phone Claim.

Cuando una Listing tenga venta y renta:

- los resultados muestran la oferta correspondiente al filtro activo;
- la portada puede mostrar ambas ofertas de forma compacta;
- la visibilidad pública de cada precio se respeta de manera independiente.

Las propiedades patrocinadas pueden aparecer dentro de la cuadrícula, pero deben
mostrar `Patrocinada` de forma inequívoca y nunca confundirse con relevancia
orgánica o antigüedad.

## Regla de antigüedad pública

La etiqueta se calcula desde la primera publicación pública comprobada, no desde
la última sincronización, edición o verificación de disponibilidad.

| Tiempo transcurrido | Etiqueta |
|---|---|
| Menos de 48 horas | `Nueva` |
| 48 a menos de 72 horas | `2 días` |
| 72 a menos de 96 horas | `3 días` |
| 96 a menos de 120 horas | `4 días` |
| 120 a menos de 144 horas | `5 días` |
| 144 a menos de 168 horas | `6 días` |
| 168 a menos de 192 horas | `7 días` |
| 192 horas o más | Sin etiqueta |

El orden `Más nuevas` usa esa misma primera publicación. La frescura de fuente y
la verificación de disponibilidad permanecen como conceptos separados.

Para datos existentes sin una primera publicación demostrable, el backfill será
conservador: no se muestra antigüedad. Los datos de Sandbox declaran fechas
explícitas para cubrir todos los estados visuales.

## Filtros

El catálogo permite filtrar por:

- operación;
- zona;
- tipo de propiedad;
- precio mínimo y máximo;
- recámaras;
- baños;
- estacionamientos;
- superficie de construcción;
- orden.

Los filtros secundarios aparecen en un panel lateral derecho en escritorio y en
un panel inferior en móvil. El panel muestra `Ver N propiedades` y aplica cambios
al confirmar. Los campos que no correspondan al tipo de propiedad no aparecen.

Si no hay resultados, se conservan todos los criterios y se explican posibles
relajaciones. Ningún filtro se elimina silenciosamente.

## Buscador con IA

### Lanzador

El control parece un campo de búsqueda, pero funciona como lanzador. Al pulsarlo:

1. se abre un diálogo sobre el contenido desenfocado;
2. el fondo queda inerte;
3. el foco pasa al campo real de conversación;
4. Maia recibe únicamente el contexto explícito mostrado al visitante.

Los ejemplos rotativos provienen preferentemente del inventario público para no
invitar a búsquedas imposibles. Existen alternativas seguras como:

- `Casas en Zapopan`;
- `Departamentos en renta`;
- `Propiedades con tres recámaras`;
- `Propiedades más nuevas`.

La rotación se detiene al enfocar, escribir o solicitar movimiento reducido. El
texto cambiante no se anuncia repetidamente a lectores de pantalla.

### Diálogo

- Centrado sobre fondo desenfocado en escritorio.
- Pantalla completa en móvil.
- Controles reales para expandir, iniciar una conversación, borrar y cerrar.
- Cerrar conserva el borrador y devuelve el foco al lanzador.
- El contexto aparece mediante etiquetas visibles, nunca de manera oculta.
- `/maia` permanece como alternativa funcional sin JavaScript.

Las sugerencias iniciales cambian con el contexto y sólo anuncian capacidades
reales, por ejemplo:

- `Buscar dentro de mi presupuesto`;
- `Comparar estas propiedades`;
- `Ayúdame a precisar mi búsqueda`.

### Resultados conversacionales

Hermes interpreta el mensaje y aclara ambigüedades. Product valida y compila los
mismos criterios que entiende el formulario del catálogo. La respuesta puede
mostrar hasta tres tarjetas y `Ver las N propiedades`.

Al continuar:

- la cuadrícula muestra el conjunto autorizado actual;
- los filtros visibles reflejan los criterios confirmados;
- la URL compartible contiene esos criterios;
- ningún requisito se amplía silenciosamente.

El envío será asíncrono. El mensaje del visitante aparece inmediatamente y se
muestra un estado verdadero como `Maia está revisando las propiedades…`. No se
simula escritura. Los fallos ofrecen reintento sin duplicar el turno.

`Nueva conversación` termina la continuidad visible y comienza una conversación
vacía respetando las reglas de retención. `Borrar conversación` elimina el
contenido que la política permita eliminar y explica qué registros operativos
independientes permanecen.

## Trabajo técnico

### Entrega 1: verdad pública y contratos

1. Incorporar la primera fecha de publicación pública y su migración conservadora.
2. Extender la búsqueda determinista con los nuevos filtros.
3. Crear una operación de búsqueda exclusiva para sesiones del sitio que sólo
   compile criterios y consulte `PUBLIC_SHARE`.
4. Devolver criterios estructurados, URL pública y referencias de Listings
   autorizadas junto con la respuesta conversacional.
5. Añadir un contrato asíncrono e idempotente para enviar y consultar turnos sin
   mantener abierta toda la cadena de proxies.
6. Impedir explícitamente que una sesión web use herramientas capaces de leer
   inventario no publicado.

### Entrega 2: experiencia pública

1. Reestructurar el encabezado global y la portada.
2. Implementar tarjetas densas, iconos, mosaicos y antigüedad.
3. Implementar filtros progresivos y vistas de cuadrícula/lista.
4. Implementar el lanzador, diálogo, desenfoque y estados asíncronos.
5. Añadir el panel de Cuenta demo sin backend de cuentas.
6. Conservar los flujos reales de guardadas, Phone Claim, Gallery, ficha técnica y
   WhatsApp.

## Verificación obligatoria

### Autoridad y comportamiento

- Una conversación web nunca obtiene una Listing que no sea `PUBLIC_SHARE`.
- La Organización se resuelve desde el host; un host sin vínculo es rechazado.
- Los criterios producidos por Hermes generan exactamente los mismos resultados
  que el formulario y la URL equivalentes.
- Los filtros, guardadas, corazón, cuadrícula/lista y controles del diálogo son
  funcionales.
- La Cuenta demo no escribe ni crea registros de identidad o autenticación.
- Los límites de antigüedad se prueban en 47:59, 48:00, 72:00, 168:00 y 192:00
  horas.
- Listings con hechos desconocidos, precio oculto, dos ofertas o patrocinio se
  renderizan sin información falsa.

### Accesibilidad y visuales

- Comparación visual a 1440 px, 1024 px y 390 px.
- Estados de diálogo cerrado, abierto, expandido, cargando, con respuesta y con
  error.
- Panel de filtros, cuadrícula, lista y cero resultados.
- Navegación completa con teclado, cierre con Escape y restauración del foco.
- Fondo inerte, bloqueo de desplazamiento y anuncios de estado accesibles.
- Movimiento reducido y teclado móvil.
- Preservación deliberada o revisión explícita de los presupuestos actuales de
  HTML, CSS y JavaScript.

## Evidencia de entrega

- Las migraciones `0032` a `0035` incorporan la primera publicación pública, la
  búsqueda exclusiva del sitio, los turnos asíncronos y el cierre anónimo.
- La búsqueda conversacional y el formulario producen el mismo conjunto y la
  misma URL canónica; una prueba real devolvió cuatro casas en Zapopan con tres
  o más recámaras, tres tarjetas en el diálogo y el enlace al conjunto completo.
- El diálogo fue comprobado cerrado, abierto, expandido, cargando, con respuesta,
  con error y después de un reintento exitoso. `Nueva conversación` cierra la
  sesión anterior y abre una sesión nueva de Hermes.
- El catálogo, la portada, la cuadrícula, la lista, los filtros y el estado sin
  resultados fueron revisados a 1440, 1024 y 390 píxeles. En móvil se comprobó
  una sola fotografía visible por tarjeta, panel inferior y diálogo de pantalla
  completa.
- Escape cierra el diálogo, restaura el foco, quita el estado inerte y vuelve a
  habilitar el desplazamiento. El movimiento reducido, los avisos accesibles y
  los estilos de foco tienen cobertura automatizada.
- La batería pública focalizada pasó con 203 pruebas; los controles finales del
  proxy de cierre y del perfil web se verificaron adicionalmente. Ruff, mypy,
  compilación de Python, sintaxis de JavaScript y validación del diff pasaron.

## Fuera de alcance

- cuentas reales de clientes;
- registro, autenticación, contraseñas o recuperación;
- perfiles persistentes o sincronización de cuenta;
- mapa público;
- búsquedas guardadas;
- historial de múltiples conversaciones;
- reescritura del frontend con otro framework;
- exposición de dirección de visita o inventario no publicado.
