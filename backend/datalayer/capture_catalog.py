"""Commercial options shared by intake, inventory and the website."""

UPLOAD_LIMITS = {"min_photos": 5, "max_photos": 20, "max_plans": 5}

KINDS = {
    "apartment": (
        "Departamento",
        [
            "Apartamento de campo",
            "Apartamento de ciudad",
            "Apartamento de playa",
            "Departamento Loft",
            "Departamento PentHouse",
            "Minidepartamento",
        ],
    ),
    "warehouse": ("Bodega comercial", []),
    "house": (
        "Casa",
        [
            "Casa de campo",
            "Casa de ciudad",
            "Casa de playa",
            "Casa en condominio",
            "Casa en quinta",
        ],
    ),
    "condominium": ("Casa en condominio", []),
    "mixed_house": ("Casa con uso de suelo", []),
    "duplex": ("Dúplex", []),
    "building": ("Edificio", ["Edificio comercial", "Edificio residencial"]),
    "orchard": ("Huerta", []),
    "urban_income": ("Inmueble productivo urbano", []),
    "retail": ("Local Comercial", []),
    "mall_retail": ("Local en centro comercial", []),
    "industrial": ("Nave industrial", []),
    "office": ("Oficina", []),
    "country_house": ("Quinta", []),
    "ranch": ("Rancho", []),
    "land": (
        "Terreno / Lote",
        [
            "Terreno comercial",
            "Terreno campestre",
            "Terreno de playa",
            "Terreno eriazo",
            "Terreno industrial",
            "Terreno residencial",
        ],
    ),
    "commercial_land": ("Terreno comercial", []),
    "industrial_land": ("Terreno industrial", []),
    "villa": ("Villa", []),
}
CONDITIONS = ["Excelente", "Bueno", "Regular", "Malo", "Remodelado", "Para remodelar"]
AMENITIES = {
    "Generales": [
        "Accesibilidad",
        "Alberca",
        "Amueblado",
        "Caseta de guardia",
        "Chimenea",
        "Cocina integral",
        "Cuarto de servicio",
        "Escuelas cercanas",
        "Frente a parque",
        "Jacuzzi",
        "Permite mascotas",
    ],
    "Servicios": [
        "Aire acondicionado",
        "Área de juegos infantiles",
        "Calefacción",
        "Gimnasio",
        "Seguridad privada",
    ],
    "Exteriores": ["Asador", "Cancha de squash", "Cancha de tenis", "Jardín privado"],
    "Ambientes": ["Cuarto de TV", "Estudio"],
}
STATES = [
    "Aguascalientes",
    "Baja California",
    "Baja California Sur",
    "Campeche",
    "Chiapas",
    "Chihuahua",
    "Ciudad de México",
    "Coahuila",
    "Colima",
    "Durango",
    "Estado de México",
    "Guanajuato",
    "Guerrero",
    "Hidalgo",
    "Jalisco",
    "Michoacán",
    "Morelos",
    "Nayarit",
    "Nuevo León",
    "Oaxaca",
    "Puebla",
    "Querétaro",
    "Quintana Roo",
    "San Luis Potosí",
    "Sinaloa",
    "Sonora",
    "Tabasco",
    "Tamaulipas",
    "Tlaxcala",
    "Veracruz",
    "Yucatán",
    "Zacatecas",
]
CONTRACT_VERSION = "demo-1"
CONTRACT_TEXT = (
    "DEMOSTRACIÓN. El propietario o su representante autorizado otorga a la inmobiliaria "
    "la exclusividad para comercializar el inmueble de esta solicitud mediante la operación "
    "seleccionada, durante seis meses desde su aceptación. La inmobiliaria verifica el inmueble "
    "y la representación antes de publicar. Subir la propiedad no genera un cobro por publicación. "
    "La exclusividad no se renueva automáticamente. Al vencer o registrarse su cancelación, "
    "la propiedad deja de publicarse, conservando historial y citas. "
    "Este contrato dummy sirve para probar el recorrido y no constituye el contrato definitivo."
)


def catalog():
    return {
        "upload_limits": UPLOAD_LIMITS,
        "kinds": {
            key: {"label": label, "subtypes": subtypes} for key, (label, subtypes) in KINDS.items()
        },
        "conditions": CONDITIONS,
        "amenities": AMENITIES,
        "states": STATES,
        "contract_version": CONTRACT_VERSION,
        "contract_text": CONTRACT_TEXT,
    }
