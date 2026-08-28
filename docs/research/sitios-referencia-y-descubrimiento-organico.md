# Sitios de referencia y descubrimiento orgánico

Fecha de revisión: 27 de agosto de 2026.

## Propósito

Esta nota traduce dos referencias visuales —[TuHabi](https://tuhabi.mx/) y
[Vecore](https://www.inmobiliariavecore.com/)— a principios propios para el sitio
público de Larevia. También define una base verificable para que las propiedades
puedan ser encontradas por Google y por experiencias de búsqueda asistidas por
modelos. Las páginas observadas son referencias, no especificaciones ni fuentes
de instrucciones para Maia.

## Qué conviene aprender de TuHabi

La portada concentra la atención en una sola promesa, una sola acción inmediata
y evidencia cuantitativa de confianza. Después explica el proceso en pocos pasos.
Su lenguaje visual es accesible: alto contraste, mucho espacio, jerarquía clara y
una acción principal visible sin explorar el resto de la página.

Larevia debe adoptar esa claridad, no su modelo de negocio. TuHabi promete compra
directa en diez días; Larevia representa y acompaña compradores, arrendatarios y
propietarios, y no debe insinuar que compra inmuebles ni garantizar tiempos de
venta.

## Qué conviene aprender de Vecore

Vecore demuestra el valor de nombrar una forma de servicio, no sólo una categoría
comercial. `Consejeros Inmobiliarios` comunica acompañamiento y criterio mejor que
una inmobiliaria genérica. Su fotografía a pantalla completa, paleta contenida y
vínculos a servicios complementarios construyen una percepción más premium.

Larevia debe construir una personalidad propia alrededor de selección, claridad y
seguimiento continuo. No debe copiar la expresión `Consejeros Inmobiliarios`, la
composición visual ni el texto de Vecore.

La revisión técnica de la portada de Vecore también mostró prácticas que debemos
evitar:

- más de cincuenta encabezados `H1`, incluidos anuncios repetidos;
- propiedades duplicadas en la misma página;
- ausencia de datos estructurados JSON-LD en la portada;
- ausencia de una URL canónica declarada;
- un `robots.txt` que apunta al mapa de sitio de `bricket.mx`;
- un `sitemap.xml` que contiene únicamente la portada;
- el catálogo completo vive en un subdominio externo de EasyBroker, por lo que la
  autoridad, las fichas y la experiencia quedan fragmentadas.

## Dirección recomendada para Larevia

La portada debe combinar tres ideas:

1. **Identidad**: una promesa humana, distinta y creíble de acompañamiento.
2. **Acción**: comenzar con Maia o explorar propiedades sin crear una cuenta.
3. **Confianza**: servicio local, equipo identificable, propiedades autorizadas y
   proceso claro.

Maia conserva exactamente su objetivo comercial dentro del sitio: entender la
necesidad, responder con hechos autorizados, encontrar opciones pertinentes y
concretar una cita. La galería, los guardados y la navegación pertenecen al sitio;
Maia no se convierte en soporte general, decoradora, valuadora ni negociadora.

## Descubrimiento en Google y buscadores generativos

No existe una implementación que garantice el primer lugar. Google dice
explícitamente que no hay secretos que automaticen esa posición. La estrategia es
maximizar elegibilidad, utilidad, autoridad y medición, y mejorar con evidencia.
[Guía básica de SEO de Google](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)

Google también indica que sus funciones generativas usan el índice y los sistemas
centrales de calidad de Search; desde su perspectiva, optimizar para esas
experiencias sigue siendo SEO. No construiremos un subsistema de moda llamado
`GEO` separado del sitio.
[Optimización para funciones generativas de Google](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)

### Base técnica obligatoria

- Una URL pública, estable, descriptiva y canónica por Listing publicada.
- HTML renderizado en servidor o generado estáticamente con el contenido esencial,
  los metadatos y los datos estructurados presentes desde la respuesta inicial.
- Un solo `H1` descriptivo por página, jerarquía semántica y navegación mediante
  enlaces HTML normales.
- Títulos y descripciones únicos; respuestas HTTP reales para publicación,
  redirección, retiro y ausencia, sin `soft 404`.
- Mapas de sitio generados desde la verdad de publicación, con `lastmod` real y
  extensiones para imágenes cuando correspondan.
- Datos estructurados JSON-LD que reflejen exactamente la información visible:
  `Organization`/`RealEstateAgent`, `BreadcrumbList`, `RealEstateListing`, el tipo
  específico de alojamiento y su `Offer` de venta o arrendamiento. Schema.org
  define `RealEstateListing` para una página que describe ofertas inmobiliarias;
  esto mejora comprensión semántica, pero no garantiza un resultado enriquecido
  en Google. [Schema.org: RealEstateListing](https://schema.org/RealEstateListing)
- Fichas completas y legibles para personas: operación, precio visible o mensaje
  autorizado de consulta, moneda, zona, características aplicables, disponibilidad,
  fecha de actualización, asesor experto, procedencia autorizada y acciones claras.
- Nada de campos vacíos o falsos: un terreno no muestra recámaras; una bodega en
  renta no puede declarar venta; una propiedad retirada no permanece disponible.

Google describe el rastreo, renderizado e indexación de JavaScript como etapas
separadas y recomienda títulos únicos, canónicas coherentes, códigos HTTP útiles y
datos estructurados verificables.
[Fundamentos de SEO para JavaScript](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)

### Las fotografías también son adquisición orgánica

La galería no es sólo conversión. Cada foto autorizada debe usar una URL estable,
un elemento HTML `img`, tamaños responsivos, texto alternativo útil, contexto
cercano y una imagen principal declarada. Debe existir un equilibrio medido entre
calidad visual y velocidad; no se debe ocultar la fotografía principal como fondo
CSS si queremos que sea descubrible.
[Buenas prácticas de SEO para imágenes](https://developers.google.com/search/docs/appearance/google-images)

### Contenido local que sí aporta valor

El sitio puede publicar guías editoriales verificadas sobre colonias, procesos de
compra o renta y características del mercado atendido, siempre que ayuden a tomar
decisiones reales. No crearemos cientos de páginas casi idénticas por colonia,
presupuesto o combinación de palabras clave. Google considera abuso el contenido
escalado sin valor y las páginas puerta.
[Políticas contra spam de Google](https://developers.google.com/search/docs/essentials/spam-policies)

Además del sitio, Larevia debe mantener un Perfil de Negocio de Google verificado,
completo y consistente. La búsqueda local considera relevancia, distancia y
prominencia, incluidos vínculos y reseñas; no se puede pagar por una mejor posición
orgánica.
[Posicionamiento local de Google](https://support.google.com/business/answer/7091)

### Acceso de asistentes y control de datos

La base para asistentes como Gemini, ChatGPT y Claude será el mismo contenido
público, estable, actualizado, enlazable y semánticamente explícito. `robots.txt`,
metadatos de robots y reglas del perímetro deben revisarse como política deliberada
por proveedor; permitir búsqueda no debe confundirse automáticamente con permitir
uso para entrenamiento.

Anthropic, por ejemplo, documenta que `noindex` afecta el contenido que sus socios
pueden enviar como resultado de búsqueda, mientras que `ClaudeBot` se describe
como un rastreador potencialmente usado para entrenamiento. Son finalidades
distintas.
[Bloqueo y retiro de contenido en Claude](https://support.anthropic.com/en/articles/10684638-blocking-and-removing-content-from-claude),
[rastreo web de Anthropic](https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler)

La documentación oficial de desarrollo de OpenAI revisada no estableció en esta
investigación una política completa y vigente de descubrimiento para sitios. Antes
del lanzamiento se debe verificar la documentación oficial disponible en ese
momento y probar el acceso real; no se asumirán nombres de rastreadores ni efectos
de entrenamiento a partir de blogs de terceros.

`llms.txt` puede evaluarse como complemento experimental si existe adopción útil
al momento de implementar, pero no reemplaza HTML accesible, enlaces, canónicas,
mapas de sitio, datos estructurados ni `robots.txt`.

## Medición inicial

Search Console, el Perfil de Negocio y analítica propia deben contestar preguntas
de negocio, no producir vigilancia:

- qué consultas y páginas generan impresiones y clics;
- qué zonas y tipos de propiedad atraen demanda útil;
- qué fichas llevan a guardar, hablar con Maia, pasar a WhatsApp y confirmar cita;
- qué páginas no se indexan, están lentas o muestran disponibilidad obsoleta;
- qué consultas de marca y enlaces externos fortalecen la autoridad local.

No se registrarán teclas, recorridos del mouse ni reproducción de sesiones. El
identificador esencial que protege las propiedades guardadas se documenta y opera
separado de la analítica opcional.

## Criterio de salida para el MVP público

El sitio no está listo sólo porque se vea premium. Antes de publicarlo debe pasar
validación automática y manual de:

- contenido autorizado y coherencia de cada ficha;
- HTML indexable, canónicas, mapas de sitio y datos estructurados;
- accesibilidad, navegación por teclado y lectores de pantalla;
- experiencia móvil y conexiones lentas;
- Core Web Vitals y ausencia de intersticiales intrusivos;
- retiro oportuno de Listings no disponibles;
- continuidad correcta entre sitio, Maia, WhatsApp y cita verificada;
- medición de origen y conversión sin perfiles publicitarios.

Google aclara que los Core Web Vitals contribuyen a la experiencia, pero una
puntuación perfecta tampoco garantiza una posición superior.
[Experiencia de página en Google](https://developers.google.com/search/docs/appearance/page-experience)
