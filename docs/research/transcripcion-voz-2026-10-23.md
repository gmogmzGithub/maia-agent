# Transcripción de notas de voz para Maia

Fecha: 23 de octubre de 2026. Etapa 5: selección tecnológica y diseño. Investigación documental, sin implementar integraciones ni ejecutar inferencia pagada. Precios consultados en USD, antes de impuestos, promociones, add-ons y reintentos. No se midieron precisión ni latencia.

## Resultado y estado de la decisión

La comparación anterior entre Deepgram y Google era demasiado estrecha. Para el piloto propongo comparar **OpenAI GPT-Transcribe, Deepgram Nova-3 y Google Gemini 3.5 Transcribe**. AssemblyAI es una cuarta alternativa. Google Cloud Chirp 3 queda como alternativa si mejora los casos difíciles. Los modelos abiertos permiten otra estrategia de operación, pero todavía no justifican sustituir la decisión de comenzar con una API externa.

No hay proveedor elegido ni ganador demostrado. El modelo conversacional de Anthropic y el transcriptor son decisiones independientes. Elegir ASR de otro proveedor no cambia la elección de Haiku.

## Qué estamos comprando

ASR convierte una grabación en texto. El harness recibe ese texto y continúa el flujo comercial. Nuestro caso es una nota de voz que ya terminó de grabarse, no una llamada en vivo. No necesitamos de inicio síntesis de voz, diarización, traducción ni timestamps por palabra.

Comparar cinco conceptos distintos evita decisiones equivocadas:

| Concepto | Ejemplo | Responsabilidad |
|---|---|---|
| Modelo | Whisper large-v3-turbo | Reconocer habla. |
| Runtime | faster-whisper, MLX | Ejecutar un modelo compatible. |
| API gestionada | Deepgram, OpenAI | Operar inferencia y exponer un servicio. |
| Catálogo y alojamiento | Hugging Face | Distribuir modelos y ofrecer opciones de inferencia. |
| Modelo conversacional | Haiku | Interpretar la transcripción y solicitar herramientas. |

## APIs gestionadas

Las cifras siguientes normalizan 1,000 minutos de audio mono. No incluyen el modelo conversacional. Una tarifa de trabajos asíncronos tampoco garantiza el mismo tiempo de respuesta que una petición directa.

| Proveedor y ruta | USD/minuto | USD/1,000 minutos | Tradeoff para el piloto |
|---|---:|---:|---|
| OpenAI `gpt-transcribe` | 0.0045 | 4.50 | API especializada; pistas de vocabulario; comprobar OGG/Opus real. |
| Deepgram Nova-3 grabado, monolingüe | 0.0043 | 4.30 | Flujo de archivo directo; configurar exclusión de MIP; extras se cobran aparte. |
| Deepgram Nova-3 grabado, multilingüe | 0.0052 | 5.20 | Evaluar si hay mezcla de idiomas; acento mexicano no exige esta modalidad. |
| Google Gemini 3.5 Transcribe | ~0.005 | ~5.00 | Estimación combinada de tokens de entrada y salida, no tarifa fija. |
| Google Cloud STT V2 estándar | 0.016 | 16.00 | Más configuración; investigar Chirp 3 y locale es-MX por ubicación. |
| AssemblyAI Universal-3.5 Pro, async | 0.0035 | 3.50 | Requiere recuperar resultado; medir espera total y borrado remoto. |
| AssemblyAI Universal-3.5 Pro, Sync | 0.0075 | 7.50 | Respuesta directa; hasta 120 s y ruta de formatos distinta. |

Fuentes de tarifas: [OpenAI](https://developers.openai.com/api/docs/models/gpt-transcribe), [Deepgram](https://deepgram.com/pricing), [Gemini](https://ai.google.dev/gemini-api/docs/pricing), [Google Cloud](https://cloud.google.com/speech-to-text/pricing), [AssemblyAI](https://www.assemblyai.com/pricing/), [diferencia Sync/async](https://www.assemblyai.com/blog/sync-api-vs-dictation-api). Las multiplicaciones son cálculo propio. Google Dynamic Batch tiene tarifa inferior y procesamiento diferido: no usarlo como equivalente al flujo interactivo.

Entre OpenAI y Deepgram mono hay USD 0.20 de diferencia por 1,000 minutos. Esa diferencia no justifica tolerar más errores en presupuestos o requisitos. El coste decisivo debe incluir operación, errores, reintentos y add-ons.

### OpenAI

La guía actual recomienda `gpt-transcribe` para grabaciones. Admite contexto y pistas de términos e idiomas. La guía fija 25 MB por archivo. Las pistas pueden ayudar con colonias y calles, pero debemos probar que no insertan términos que nadie dijo. [Guía](https://developers.openai.com/api/docs/guides/speech-to-text).

No iniciar una integración nueva con `whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` o `gpt-4o-transcribe-diarize`: el aviso actual anuncia su retirada el **26 de febrero de 2027**. El retiro de una API no retira los pesos abiertos de Whisper. [Deprecaciones](https://developers.openai.com/api/docs/deprecations).

Hay una discrepancia de formatos: la guía no enumera OGG, mientras que la referencia del endpoint sí. No queda garantizada explícitamente cada combinación OGG/Opus. Antes de añadir conversión, probar un archivo real y su Content-Type. [Referencia](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create).

### Anthropic

Haiku 5.5 documenta entrada de texto e imágenes y salida de texto. El catálogo revisado no documenta un servicio ASR nativo. Por tanto, no enviaríamos la nota directamente a Haiku: enviaríamos la transcripción. Una función de dictado en una aplicación no demuestra capacidad de audio en la API. [Haiku](https://platform.claude.com/docs/en/models/haiku-5-5/overview), [catálogo](https://platform.claude.com/docs/en/models/overview).

### Google: dos productos especializados y una alternativa general

**Gemini 3.5 Transcribe** es ASR dedicado, distinto del Gemini general. Documenta español latinoamericano, vocabulario personalizado y audio de hasta una hora, con límites menores al activar algunas funciones. No necesitamos diarización ni timestamps. [Modelo](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe).

Comenzaría con modo `verbatim`. El modo `smart` puede limpiar repeticiones y resolver autocorrecciones; para nosotros conviene preservar lo dicho antes de que Haiku lo interprete. Ejemplo: conservar “el martes, no, el miércoles” permite revisar la corrección sin el audio original. [Modos y formatos](https://ai.google.dev/gemini-api/docs/transcribe).

**Cloud STT V2 / Chirp 3** ofrece una ruta distinta. La tabla V2 incluye es-MX en ubicaciones us/eu; la página específica de Chirp 3 enumera menos variantes de español. Resolver esa discrepancia con una petición de prueba antes de integrar. El reconocimiento síncrono limita duración/tamaño; las rutas más largas pueden añadir Cloud Storage y trabajo asíncrono. [Idiomas](https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages), [Chirp 3](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3), [límites](https://docs.cloud.google.com/speech-to-text/docs/quotas).

**Gemini general** también puede transcribir mediante instrucciones, pero añade libertad generativa que debemos evaluar. Daría prioridad al ASR dedicado para una tarea donde queremos conservar literalmente cantidades y negaciones. Esta prioridad es una recomendación de diseño, no un resultado de precisión medido. [Audio understanding](https://ai.google.dev/gemini-api/docs/audio).

### Deepgram y AssemblyAI

Nova-3 documenta español y soporte de audio grabado. Probar OGG/Opus directo. Keyterm prompting es un extra tarifado; comparar el coste con y sin glosario. [Idiomas](https://developers.deepgram.com/docs/models-languages-overview/), [formatos](https://developers.deepgram.com/docs/supported-audio-formats), [keyterms](https://developers.deepgram.com/docs/keyterm).

AssemblyAI Universal-3.5 Pro admite español. Su API async y su API Sync difieren en precio, formatos y retención. No extrapolar soporte OGG del servicio async a Sync. Universal-3.6 Pro es una ruta de streaming y no debe asumirse disponible para archivos por compartir nombre. [Modelo e idiomas](https://www.assemblyai.com/blog/universal-3-5-pro-code-switching-contextual-prompting), [changelog](https://www.assemblyai.com/changelog), [integración oficial](https://github.com/AssemblyAI/assemblyai-skill/blob/main/skills/assemblyai/SKILL.md).

## Modelos abiertos en Hugging Face

Hugging Face no es un único transcriptor. La ficha del modelo, su licencia y el lugar donde se ejecuta son decisiones separadas.

| Modelo | Español y licencia documentados | Por qué investigarlo |
|---|---|---|
| [Whisper large-v3](https://huggingface.co/openai/whisper-large-v3) | Multilingüe; Apache-2.0 según su ficha. | Referencia para comparar modelos abiertos. |
| [Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | Multilingüe; MIT. | Versión con decodificador reducido; evaluar intercambio entre velocidad y precisión. |
| [NVIDIA Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Español; CC-BY-4.0. | Modelo de 600M; no confundir con variantes solo en inglés. |
| [Qwen3-ASR 0.6B / 1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | Español; Apache-2.0. | Dos tamaños para evaluar recursos frente a precisión. |
| [IBM Granite Speech 5.0 2B](https://huggingface.co/ibm-granite/granite-speech-5.0-2b) | Español; Apache-2.0. | Vocabulario personalizado y ruta documentada con MLX para Apple Silicon. |

Las licencias corresponden a esas fichas/versiones, no a cualquier derivado. La ficha de Granite se verificó también en su [README oficial](https://huggingface.co/ibm-granite/granite-speech-5.0-2b/raw/main/README.md). Ninguna ficha demuestra qué modelo reconoce mejor “Ciudad Granja” en una nota de WhatsApp.

`faster-whisper` es un runtime compatible con Whisper, no otro modelo. MLX es otra vía de ejecución para hardware Apple compatible. No hemos verificado chip, memoria ni rendimiento de la máquina del piloto. [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [MLX Audio](https://github.com/Blaizzy/mlx-audio).

Tres formas de operar:

1. **Proveedor gestionado compatible:** pago por uso; comprobar disponibilidad exacta de modelo y política del proveedor.
2. **Endpoint dedicado:** pagamos recursos mientras se inicializan y ejecutan, incluso sin audios durante parte de ese tiempo. Escalar a cero reduce gasto pero puede introducir arranque en frío.
3. **Máquina propia:** evitamos una tarifa externa por minuto y asumimos memoria, capacidad, concurrencia, actualizaciones y disponibilidad. Compartir recursos con la aplicación debe medirse.

Fuentes: [Inference Providers](https://huggingface.co/docs/inference-providers/pricing), [Endpoints](https://huggingface.co/docs/inference-endpoints/pricing), [autoscaling](https://huggingface.co/docs/inference-endpoints/guides/autoscaling).

No asignar USD 0/minuto a un modelo abierto. Para compararlo: coste de cómputo, operación y capacidad ociosa dividido entre minutos procesados, más almacenamiento y transferencia cuando correspondan. Con poco tráfico, una API de USD 4–5 por 1,000 minutos puede costar menos que mantener capacidad propia disponible. Esta conclusión depende de carga y hardware; no es un benchmark.

## Retención: plataforma y proveedor

La decisión aceptada es conservar la transcripción y eliminar nuestro audio temporal. La eliminación local no borra automáticamente copias enviadas al proveedor.

| Ruta | Qué está documentado y qué exige el diseño |
|---|---|
| OpenAI `/v1/audio/transcriptions` | La tabla específica indica sin entrenamiento, sin retención de monitoreo de abuso ni estado de aplicación. No extrapolar políticas de otros endpoints ni afirmar ausencia de metadata. [Controles](https://developers.openai.com/api/docs/guides/your-data). |
| Deepgram | Configurar `mip_opt_out=true`; documentación indica no conservar contenido tras responder, con metadata operativa conservada. Desde marzo de 2026 excluir MIP no cambia las tarifas PAYG/Growth. [Datos](https://developers.deepgram.com/trust-security/your-data), [cambio tarifario](https://developers.deepgram.com/changelog/2026/3/5). |
| Gemini | El nivel pagado estándar no usa contenido para mejora; eso no equivale a cero retención. Files API conserva archivos hasta 48 h o borrado manual. Revisar también estado/logs del endpoint elegido. [Files](https://ai.google.dev/gemini-api/docs/files), [términos](https://ai.google.dev/gemini-api/terms). |
| AssemblyAI | Sync y async tienen políticas diferentes. Configurar opt-out y, para async, TTL/borrado aplicable. No prometer eliminación instantánea de todas las copias. [Retención](https://www.assemblyai.com/docs/data-retention-and-model-training). |
| Google Cloud STT V2 | Resolver la política de la ruta concreta, incluido Cloud Storage. La FAQ V1 no demuestra por sí sola cero retención en V2. [FAQ V1](https://docs.cloud.google.com/speech-to-text/docs/v1/data-usage-faq). |

Para el diseño posterior: temporales con limpieza por éxito, fallo y vencimiento; sin audio en trazas o backups; transcripción asociada al mensaje; estado del trabajo y metadatos operativos mínimos. Las copias temporales remotas requieren su propio borrado cuando existan. Los valores de TTL y los límites de archivo siguen pendientes.

## Evaluación propuesta, todavía no ejecutada

Cinco audios sirven para comprobar integración, no para declarar ganador. Propongo comenzar con 30 clips de prueba, transcritos y revisados manualmente, y ampliar con errores del piloto. No es una muestra estadística de producción. Usar material preparado para esta evaluación, sin conservar audios reales de prospectos fuera de la política acordada.

Casos: Guadalajara/Zapopan/Tonalá/Tlaquepaque; nombres de colonias y calles; presupuesto mensual frente a precio de compra; “hasta”, “mínimo” y “no”; mascotas; horarios y autocorrecciones; ruido; silencios; audio cortado; una frase en inglés; notas cercanas a los límites elegidos.

| Medida | Qué responde |
|---|---|
| Error por palabra, WER | ¿Cuánto difiere del texto esperado? Es diagnóstico, no criterio único. |
| Exactitud de campos críticos | ¿Conserva importe, periodicidad, operación, zona, negación y fecha? |
| Omisiones y adiciones | ¿Descarta un requisito o inventa palabras? Incluir silencio y ruido sin habla. |
| Latencia completa | Desde mensaje recibido hasta transcripción disponible, incluyendo cola, descarga, conversión y red. |
| Fallos y reintentos | ¿Qué ocurre con timeout, formato inválido, duplicado y rate limit? |
| Coste efectivo | ASR, extras, conversión, almacenamiento y reintentos por audio útil. |
| Borrado | ¿Quedan archivos locales o remotos después de éxito/fallo/vencimiento? |

Un glosario debe contener términos posibles, no una respuesta esperada. Probar con y sin él y con audios que no pronuncien esos términos. No pasar presupuestos inferidos para forzar una lectura.

Comparar primero los tres candidatos propuestos con los mismos archivos y condiciones. Elegir uno para el piloto. Un adaptador pequeño permite sustituirlo; no hace falta implementar fallback entre varios proveedores. Si falla la transcripción tras el límite acordado, pedir el mensaje escrito y registrar el fallo.

Regla comercial: transcribir “el martes, no, miércoles” no autoriza agendar nada sin pasar por el flujo determinístico de disponibilidad y confirmación. Una transcripción fluida tampoco demuestra que una cantidad ambigua sea correcta.

## Decisiones que siguen abiertas

- Proveedor y modelo finales, después de pruebas representativas.
- Límite de duración/tamaño y tiempo de respuesta objetivo.
- Vocabulario inicial y aceptación de errores críticos.
- Ruta de formatos y necesidad real de conversión.
- Retención remota de la integración exacta y prueba de limpieza.
- Cotas de concurrencia/reintentos dentro del presupuesto global del sistema.

Esta investigación no autoriza iniciar la etapa 6 ni desplegar servicios.
