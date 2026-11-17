# Instrucciones del proyecto

Guillermo Gomez es el ingeniero responsable. Mantén las soluciones simples y la comunicación concisa, en español y sin rayas largas.

Antes de crear o mover código, consulta `docs/architecture/code-structure.md`. Respeta sus módulos: `frontend/src/main-website`, `crm`, `shared`; y `backend/agent`, `harness`, `worker`, `datalayer`, `llm_ops`, `api`.

Las entradas de Next.js permanecen en `frontend/src/app`; las pantallas se implementan en su módulo. Los imports nuevos de modelos usan `datalayer.models`. `backend/core/models.py` existe únicamente para las migraciones históricas. Conserva el identificador Django `core`, las tablas y los identificadores públicos al reorganizar archivos.

En refactorizaciones estructurales conserva comportamiento, contrato HTTP, instrucciones del agente y datos. Ejecuta las pruebas existentes, comprueba que no aparecen migraciones y valida la compilación del frontend. Para comprobar el proxy real con la plataforma arrancada, ejecuta `backend/scripts/check_web_routes.py` desde el entorno Python del backend.

No leas ni publiques `.env`. No hagas commits, pushes ni cambios de rama sin autorización. No añadas funciones del siguiente incremento durante una reorganización. Avisa explícitamente al cambiar de etapa del plan.
