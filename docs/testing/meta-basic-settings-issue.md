# Meta: fallo al abrir Basic

Verificado el 7 de noviembre de 2026. Basic falla en la aplicación anterior y funciona en la nueva `Maia App`, ID `1123980987048265`. La copia del secreto y la configuración del webhook siguen pendientes.

## Reproducción

1. Iniciar sesión en Meta for Developers con la cuenta administradora.
2. Abrir `real-estate-lead-agent`, ID `1407218091330259`.
3. Entrar en App settings → Basic.

Resultado: «This page isn't available right now». Guillermo confirmó el mismo fallo en incógnito. Cambiar `locale=es_LA` traduce el mensaje, pero no corrige el fallo. La URL sin `business_id` también terminó en la página con el contexto de empresa y el mismo error.

## Comparaciones

- My Apps identifica la cuenta como administradora.
- Dashboard, Roles, Required actions y Advanced cargan.
- Required actions indica que no hay acciones pendientes.
- El estado oficial de Meta no reportaba incidencias en Graph API ni WhatsApp al consultarlo. No acredita que Basic funcione.
- El 6 de noviembre, una consulta autenticada de lectura al identificador del número de prueba respondió HTTP 200. Esa prueba no valida el webhook.

## Consola

Basic registra un error de JavaScript:

```text
ErrorUtils caught an error:
Converting to a string will drop content data.
Hash="undefined"
Translation="Log In-App Purchases Automatically (Recommended) {log-in-tooltip}"
Content="Context not logged."
```

El error puede estar relacionado con la página fallida; no demuestra su causa. No se modificaron permisos ni controles de seguridad para evitarlo.

## Opciones pendientes

Guillermo autorizó crear otra aplicación y conservar la anterior. Completó la creación de `Maia App`, con WhatsApp y el portfolio `Gmo Gmz`. Su página Basic carga y muestra App secret y Show. La comparación apunta a un fallo ligado a la aplicación anterior o a su configuración, pero no identifica la causa interna.

- Copiar el secreto de Maia App localmente, sin compartirlo en el chat.
- Configurar WhatsApp en la nueva aplicación y verificar sus identificadores y token. No mezclar el secreto nuevo con las credenciales de la aplicación anterior.
- Verificar el webhook público con la nueva aplicación y probar recepción y respuesta.
- Si se reporta el fallo anterior a Meta, adjuntar URL, reproducción, captura y error de consola. No adjuntar tokens, cookies ni un HAR sin revisar.

No sustituir el secreto de aplicación por el client token ni desactivar la validación de firmas.
