# Cuentas y verificación: trabajo posterior

Actualización del 20 de noviembre de 2026: el recorrido actual de registro, verificación por email y recuperación quedó incluido en la aceptación BETA del incremento 6. Siguen pendientes el rediseño completo de acceso durante captación y la verificación de posesión del celular. Las notas siguientes conservan su cronología; los bloqueos iniciales de correo local no describen el estado actual de Resend.

Solicitud de Guillermo, 7 de noviembre de 2026. Registrar para una etapa posterior; no implementar este alcance durante la validación actual de captación. No se asigna todavía un número de incremento ni una fecha.

## Problema

La creación de cuenta interrumpe el formulario de captación de una manera que Guillermo considera poco amigable. El flujo actual de registro y verificación no equivale a una solución completa de cuentas para clientes reales.

## Dos trabajos distintos

1. **Experiencia de captación:** rediseñar cuándo y cómo se pide crear cuenta o iniciar sesión, explicar su beneficio y conservar el avance, las fotos y el contexto. Registrar este ajuste también en las [mejoras transversales](../testing/mejoras-transversales.md).
2. **Cuentas completas:** diseñar e implementar todo el recorrido de registro, acceso y verificación real de email y celular, incluidos errores y recuperación. Guillermo pidió hacerlo correctamente y de forma completa en otra etapa.

## Alcance por definir para cuentas completas

- Registro, inicio y cierre de sesión, recuperación de contraseña y reanudación del trámite original.
- Entrega real de verificación por email y celular, selección de proveedores y configuración por entorno.
- Verificación de posesión del celular; confirmar que está bien escrito no equivale a verificarlo.
- Enlaces o códigos vencidos, incorrectos o ya utilizados; reenvío, esperas y límites de intentos.
- Email o teléfono ya registrados y cambio de datos de contacto, conservando autorización y privacidad.
- Comunicación clara de qué falta verificar y cómo resolver un bloqueo sin perder el formulario.
- Recorridos completos en móvil y escritorio, incluidos fallos del proveedor y cierre o recarga de la página.

Los puntos anteriores delimitan la revisión futura; sus mecanismos, reglas y proveedores todavía no están acordados. Mantener los requisitos actuales hasta autorizar su sustitución.

## Evidencia actual y criterio de cierre

Guillermo confirmó que pudo continuar tras abrir el mensaje de verificación guardado localmente. El correo no se entregó a su buzón: la instancia usa el backend de archivos de desarrollo. La verificación de celular todavía no existe; solo se confirma el número escrito.

El uso del correo local permite probar captación, pero no acredita el cierre del flujo de cuentas. La etapa futura requiere comprobar registro, entregas reales, verificación de ambos canales, recuperación y casos de error con los proveedores configurados.

## Ajustes dentro del incremento 6

Actualización del 15 de noviembre de 2026: Resend está activado y Guillermo confirmó recepción real del correo de registro. Por nueva solicitud, el email debe verificarse antes de acceder a Mis propiedades o al formulario con una cuenta iniciada. Se añadió la pantalla de espera con reenvío y cambio de cuenta, junto con el bloqueo correspondiente en API. La comprobación manual de todo el recorrido continúa pendiente; la verificación del celular y los demás mecanismos futuros conservan su alcance posterior.

En el trabajo nocturno se mejoró la explicación contextual del registro, el foco y la presentación móvil; se conserva el avance al volver al formulario. El enlace de aprobación abre la solicitud tras iniciar sesión y no se reutiliza al empezar una propiedad nueva. Hay opción de mostrar u ocultar contraseña. Se preparó Resend para los correos actuales de cuenta y captación, con activación externa todavía pendiente. Estos ajustes no completan la verificación de posesión del celular ni sustituyen el alcance futuro descrito arriba.
