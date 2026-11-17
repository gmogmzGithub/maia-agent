# Conectar Google Calendar

La configuración requiere una cuenta administradora del proyecto Google. No compartas secretos por chat ni los guardes en el repositorio.

1. Selecciona el proyecto de Maia en [Google Cloud](https://console.cloud.google.com/) y habilita **Google Calendar API**.
2. Configura **Google Auth Platform**: Branding, Audience y Data Access. Para cuentas Gmail personales, usa audiencia External. Si usas Testing, añade como usuarios de prueba las cuentas que conectarás; los permisos Calendar caducan a los siete días. La publicación y verificación para el piloto deben revisarse antes de incorporar al equipo.
3. En **Clients**, crea un cliente OAuth de tipo **Web application**. Registra como URI de redirección autorizada exactamente `http://localhost:3000/api/calendar/callback` para pruebas en esta computadora. Para acceso remoto, usa el dominio HTTPS estable y esa misma ruta. El valor debe coincidir con `GOOGLE_REDIRECT_URI`.
4. Configura localmente estas variables en `.env`, conservando los valores existentes de otras integraciones:

   ```dotenv
   GOOGLE_CLIENT_ID=
   GOOGLE_CLIENT_SECRET=
   GOOGLE_REDIRECT_URI=http://localhost:3000/api/calendar/callback
   CALENDAR_ENCRYPTION_KEY=
   ```

5. Genera la clave de cifrado una sola vez desde tu terminal y copia el resultado en `CALENDAR_ENCRYPTION_KEY`:

   ```sh
   cd /Users/el-men/Workspace/maia-agent/backend
   uv run --frozen python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

   Conserva esa clave. Cambiarla impide descifrar los permisos guardados y exige reconectar las cuentas. Backend y worker deben recibir la misma clave.

6. Tras reconstruir la versión que incluye citas, recarga el entorno:

   ```sh
   docker compose up -d --force-recreate backend worker
   ```

7. Abre **CRM → Asesores → Conectar Google Calendar**. El propietario inicia sesión en Google y autoriza. De regreso en el CRM, revisa el email mostrado y pulsa **Confirmar cuenta del asesor**.

Maia solicita `openid`, `email`, `calendar.events.owned` y `calendar.freebusy`. La consulta de ocupación no trae detalles de compromisos personales. El permiso de eventos es más amplio; el backend limita su uso a las citas registradas por Maia. Conectar Google no concede acceso al CRM.

Fuentes: [configuración de Google Auth Platform](https://developers.google.com/workspace/calendar/api/quickstart/python), [OAuth para aplicaciones web](https://developers.google.com/identity/protocols/oauth2/web-server), [permisos Calendar](https://developers.google.com/workspace/calendar/api/auth), [caducidad en Testing](https://support.google.com/cloud/answer/15549945?hl=en).
