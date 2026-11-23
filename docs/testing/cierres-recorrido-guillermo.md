# Prueba manual desde la propiedad

Aceptado por Guillermo el 22 de noviembre de 2026. Comprobó conservación de la ficha al despublicar, renta desde su teléfono y corrección del precio con ambos importes, correo y fecha en el historial. Después reportó satisfactorias las pruebas restantes de captación externa y Retirar por cancelación, y pidió cerrar este recorrido. Esta guía sustituye la navegación anterior por Cierres y queda como referencia de regresión.

## 1. Revisar la ficha de origen

Abre [CRM local → Propiedades](http://localhost:3000/crm). Usa una propiedad dedicada a pruebas, creada desde Nueva propiedad o desde captación externa. Verifica dirección privada, estado, municipio, colonia, superficies y características desde su alta. Los datos desconocidos permanecen vacíos. El precio anunciado se conserva separado del resultado final.

La sesión activa del equipo permite registrar el resultado sin habilitar otro permiso, también para administradores. Cada cambio toma el correo del autor de la sesión y lo conserva con su fecha. El formulario no pide ni permite elegir ese correo.

## 2. Registrar una venta o renta realizada

1. En la propiedad de prueba, pulsa Marcar vendida o Marcar rentada.
2. Revisa los datos heredados. No debe pedir otra vez dirección, superficies ni características. Si falta algo, usa Editar ficha de origen.
3. Introduce precio final **3,100,000.50 MXN** y una fecha válida para el caso de prueba. Marca Registro de prueba.
4. Pulsa Revisar resultado, comprueba el resumen y confirma expresamente.
5. Recarga y consulta Historial desde la propiedad, también en el teléfono.

Resultado esperado: propiedad vendida/rentada y despublicada; precio anunciado original intacto. El resultado conserva una copia de los datos del inmueble y el precio/fecha finales. La marca de prueba no simula los efectos, por eso se usa una propiedad dedicada.

## 3. Retirar sin operación

Usa otra propiedad de prueba. Pulsa Retirar y explica «El propietario canceló el contrato de comercialización». Recarga y abre su Historial.

Resultado esperado: conserva dirección, características y datos comerciales; los acuerdos aceptados conservan su copia aunque terminen. Queda retirada y despublicada, sin venta/renta ni precio final inventados. Volver a comercializar requiere acción expresa y revisión, sin reactivar contratos anteriores automáticamente.

## 4. Comprobar correcciones

Desde la propiedad vendida/rentada de prueba, corrige el precio con un motivo. El historial debe conservar ambos importes y quién hizo el cambio. Anular corresponde a una operación que nunca ocurrió; revertir corresponde a una operación que ocurrió y después se deshizo. Ninguna acción publica automáticamente.

Los históricos incompletos se cargan excepcionalmente desde Operaciones anteriores. No forman parte de la primera prueba. Tampoco se requiere reactivar WhatsApp. Siguen separados la credencial de operación continua y los textos con Santiago.
