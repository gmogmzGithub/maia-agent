# Actualización de seguridad de Next.js

22 de noviembre de 2026. Solicitada por Guillermo antes de iniciar sus pruebas manuales del registro de cierres.

## Cambio aplicado

Next.js pasó de **16.4.2 a 16.4.6**, manteniendo la rama 16 y la política de versiones del proyecto: `next: ^16.4.6` en `frontend/package.json` y resolución 16.4.6 en `pnpm-lock.yaml`. Se actualizaron los paquetes asociados `@next/env` y `@next/swc-*`. React y React DOM permanecen en sus versiones instaladas 19.3.1; no se cambió el gestor de paquetes ni se ejecutaron migraciones de arquitectura.

La [publicación oficial de seguridad de noviembre](https://nextjs.org/blog/november-2026-security-release) identifica 16.4.5 como versión corregida. Se eligió la versión estable posterior [16.4.6](https://github.com/vercel/next.js/releases/tag/v16.4.6), confirmada en el registro npm y las notas del mantenedor.

## Verificación

| Comprobación | Resultado |
| --- | --- |
| Auditoría de dependencias de producción antes | 7 avisos moderados, todos asociados a Next.js. |
| Auditoría de producción después | 0 avisos conocidos. |
| Auditoría completa, incluidas dependencias de desarrollo | 0 avisos conocidos, 129 dependencias auditadas. |
| Backend | 299 correctas, 2 opcionales omitidas. |
| Frontend | 59 correctas. |
| Tipos TypeScript | Correctos. |
| Compilación nativa y compilación de imagen Docker | Correctas, Next.js 16.4.6, sin la alerta anterior. |
| Comprobación de Django | Sin incidencias. |
| Versión del contenedor web en ejecución | 16.4.6. |

Las auditorías consultaron el registro npm oficial el 22 de noviembre de 2026. El resultado describe los avisos conocidos por esa fuente en ese momento, sin constituir garantía de ausencia de cualquier vulnerabilidad.

Se repitió el recorrido de navegador de cierres: sesión y permiso explícito, captura con el componente Google, borrador, resumen, confirmación, corrección exacta de centavos, anulación, reapertura, recarga y vista móvil. El backend y la base PostgreSQL fueron reales y temporales; Google y el mapa se simularon para ese recorrido. No se enviaron mensajes reales ni se reactivó el piloto de WhatsApp. Los recursos temporales se eliminaron al terminar.

## Aplicación local

Se reconstruyó y actualizó únicamente el servicio web del proyecto existente `maia-incremento1`, con los mismos archivos de configuración de la plataforma. Backend, worker y base conservaron sus servicios. Se comprobó 16.4.6 desde el contenedor nuevo en ejecución.

Respondieron HTTP 200 la portada, CRM, cuenta/formulario del propietario, salud, inventario y una ficha pública. El registro privado respondió HTTP 403 sin sesión y con `Cache-Control: private, no-store`. La prueba del proxy completó creación y lectura de una conversación, con sesión y CSRF, sin redirigir el POST.

No se leyeron ni modificaron archivos de credenciales, ni se hicieron commits, pushes o cambios de rama.

## Siguiente paso

Guillermo inicia la [aceptación manual](cierres-recorrido-guillermo.md) con un histórico marcado **Registro de prueba**, sin vincular ofertas actuales. Su primer resultado pendiente es guardar y volver a abrir un borrador con el día faltante. La confirmación debe permanecer bloqueada hasta completar los datos obligatorios.
