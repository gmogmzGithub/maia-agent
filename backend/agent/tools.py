"""Tool descriptions and input contract exposed to the sales agent."""

from datalayer.schemas import (
    ContactInput,
    ContactNameInput,
    InterestInput,
    ReplyProposal,
    SearchRequest,
)

FINAL_TOOL = {
    "name": "propose_reply",
    "description": "Termina el turno proponiendo la respuesta completa: bloques ordenados de texto, fichas y un control si es necesario; propósito y pendiente siguiente. No ejecuta operaciones ni envía. Úsala sola, después de recibir los resultados de las herramientas. property_ids solo de fichas autorizadas en este turno. visit requiere proposal_id vigente. contact muestra el formulario del website. El texto de cada bloque va al cliente; la continuidad es interna. No añadas texto fuera de esta herramienta.",
    "input_schema": ReplyProposal.model_json_schema(),
}

TOOLS = [
    {
        "name": "record_name",
        "description": "Guarda cómo se llama la persona cuando ella lo dice o lo corrige explícitamente. Conserva su nombre tal como lo expresó. No infieras nombres de propiedades, asesores, terceros ni perfiles. No registra interés, citas, permisos ni seguimientos. Úsala aunque todavía no haya celular.",
        "input_schema": ContactNameInput.model_json_schema(),
    },
    {
        "name": "stop_followup",
        "description": "Detiene seguimientos cuando la persona pide no recibir mensajes. Llámala antes de confirmar la baja; solo stopped=true acredita que se guardó. No cierra la atención entrante ni borra historial. Nunca usar por una búsqueda normal ni por rechazar una propiedad.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "visit_slots",
        "description": "Consulta hasta tres horarios reales de visita. Si el prospecto no indicó fecha, omite day: el código busca los próximos disponibles dentro del horizonte permitido. Si indicó una fecha, usa day YYYY-MM-DD. Usa offset para más opciones de la misma consulta. No reserva. Para reprogramar incluye appointment_id de ESTA conversación.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "integer"},
                "day": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "appointment_id": {"type": "string"},
            },
            "required": ["property_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_visit",
        "description": "Prepara la confirmación visual de creación, reprogramación o cancelación. No crea ni cambia la cita: solo el clic del prospecto confirma. Requiere celular previamente confirmado. start es ISO8601 hora Guadalajara. Para move/cancel usa appointment_id de ESTA conversación; para create property_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "move", "cancel"]},
                "property_id": {"type": "integer"},
                "start": {"type": "string"},
                "appointment_id": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_visit_help",
        "description": "Registra una solicitud pendiente al asesor: sin horarios, fecha fuera del horizonte, falta de conexión o preferencia que requiere coordinación humana. No confirma ninguna cita.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string", "maxLength": 1000}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_interest",
        "description": "Registra interés EXPRESO en propiedades y/o solicitud humana. No uses esta herramienta por una búsqueda exploratoria. human_requested=true solo si pide un asesor, una llamada o coordinar una visita. Incluye resumen fiel y nombre si lo expresó, sin inventar. Puede registrar una solicitud humana sin celular. Si el mensaje contiene un celular explícito y único, el backend lo prepara para confirmación en el website.",
        "input_schema": InterestInput.model_json_schema(),
    },
    {
        "name": "prepare_contact",
        "description": "Prepara el celular expresado por el prospecto para confirmación explícita en el website. No lo registra todavía; el usuario debe confirmar el número en el formulario. Nombre opcional. Antes usa record_interest.",
        "input_schema": ContactInput.model_json_schema(),
    },
    {
        "name": "search_properties",
        "description": "Busca inventario publicado con filtros determinísticos. Actualiza solo requisitos expresados por el prospecto. Devuelve tres propiedades, campos sin confirmar y next_offset.",
        "input_schema": SearchRequest.model_json_schema(),
    },
    {
        "name": "get_property",
        "description": "Obtiene datos públicos vigentes. Usa show_card=false para contestar detalles o comparar sin ficha. Una ficha ya mostrada no se repite. Solo cuando la persona pida explícitamente verla nuevamente, usa show_card=true y show_again=true. Consultar datos no requiere volver a presentar la propiedad.",
        "input_schema": {
            "type": "object",
            "properties": {
                "property_id": {"type": "integer", "minimum": 1},
                "show_card": {"type": "boolean", "default": True},
                "show_again": {"type": "boolean", "default": False},
            },
            "required": ["property_id"],
            "additionalProperties": False,
        },
    },
] + [FINAL_TOOL]
