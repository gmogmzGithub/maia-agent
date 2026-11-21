# Operación continua de Maia en esta Mac

Configurado el 16 de noviembre de 2026 para el piloto BETA. No sustituye el respaldo externo ni prepara por sí solo producción.

## Estado instalado

- Mac conectada a corriente. `local.maia.awake` mantiene `caffeinate -is`: evita suspensión por inactividad y solicita evitar suspensión del sistema con corriente. La pantalla puede apagarse y la sesión puede bloquearse.
- OrbStack es el motor Docker de esta Mac. `local.maia.engine` abre OrbStack en segundo plano al iniciar sesión. Su proceso lanzador termina con código 0 después de abrir la aplicación; no es un fallo.
- PostgreSQL, backend, worker y web tienen `restart: unless-stopped`, tanto en `compose.yaml` como en los contenedores actuales. Una detención manual se respeta.
- `local.maia.tunnel` mantiene `cloudflared` con el túnel `maia-sandbox` y la configuración local existente. macOS reinicia el proceso si termina. Se retiró el proceso manual anterior.
- Los tres servicios se instalan en `~/Library/LaunchAgents/`. Sus logs están en `~/Library/Logs/Maia/`. No contienen claves añadidas por el instalador.

Instalación repetible, desde la raíz del proyecto:

```sh
python3 scripts/setup-always-on-macos.py
```

No lee ni modifica `.env`, no recrea contenedores, no cambia proveedores ni envía mensajes. Requiere que existan los cuatro contenedores de Maia. Conserva los archivos de Compose de Resend y Google al actualizar la plataforma.

## Condiciones para mantener el piloto disponible

Mantener corriente e Internet, OrbStack abierto y la sesión iniciada. El equipo reporta batería interna: si es el portátil, dejar la tapa abierta. No elegir Suspender, cerrar sesión ni detener OrbStack durante el piloto. Bloquear la pantalla sí es compatible con esta configuración.

Los agentes arrancan **al iniciar sesión**, no antes de desbloquear la Mac. Después de un reinicio o corte de corriente hay que desbloquear e iniciar sesión. No se activó inicio de sesión automático ni se reinició el equipo para comprobarlo. `caffeinate` no garantiza disponibilidad con tapa cerrada, apagado o suspensión forzada. La caída de Internet interrumpe el acceso público hasta que se recupere la conexión del túnel.

El token de Meta se renovó el 16 de noviembre; no se comprobó su duración. La disponibilidad de la Mac no evita que caduquen credenciales externas.

## Verificación realizada

- Instalador: sintaxis válida, archivos plist aceptados por `plutil` y segunda ejecución sin reinstalar servicios activos.
- macOS confirmó `PreventSystemSleep=1` y `PreventUserIdleSystemSleep=1`, asociados a `caffeinate`.
- Los cuatro contenedores quedaron en ejecución con `unless-stopped`.
- Al terminar el proceso del túnel, macOS creó otro PID automáticamente. La dirección pública recuperó `/api/health` con HTTP 200 y `{"ok": true}`. Hubo una interrupción transitoria durante la reconexión; no se promete recuperación instantánea.
- Una detención explícita desde Docker se respetó y se volvió a iniciar la web. Después se terminó el proceso principal desde dentro del contenedor: Docker lo reinició automáticamente, con `RestartCount=1` y estado `running`. La salud local y pública respondió HTTP 200.
- El proxy real pasó `backend/scripts/check_web_routes.py` después de la recuperación: creación y lectura de conversación correctas. El arranque tras reiniciar la Mac queda sin prueba física.

Comprobaciones de solo lectura:

```sh
docker compose ps
launchctl print gui/501/local.maia.tunnel
launchctl print gui/501/local.maia.awake
pmset -g assertions
curl --http1.1 -fsS https://sandbox.elmenlabs.com/api/health
```

Para volver a permitir suspensión por inactividad, descargar `local.maia.awake` con `launchctl bootout gui/501/local.maia.awake`; eliminar su plist si tampoco debe iniciarse en el próximo acceso. La configuración global de energía de macOS no se modificó.

Referencias: [reinicio de contenedores](https://docs.docker.com/engine/containers/start-containers-automatically/), [agentes de Cloudflare en macOS](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/as-a-service/macos/), [OrbStack por línea de comandos](https://docs.orbstack.dev/headless). Las opciones de suspensión se contrastaron con `man caffeinate` en esta Mac.
