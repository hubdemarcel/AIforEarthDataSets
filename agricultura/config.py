"""Configuración: zonas piloto y catálogo de clases de cobertura/cultivo."""

# bbox en grados: (lon_min, lat_min, lon_max, lat_max)
ZONAS = {
    "tequila": {
        "nombre": "Valle de Tequila–Amatitán, Jalisco",
        "bbox": (-103.90, 20.78, -103.68, 20.93),
    },
    "los_altos": {
        "nombre": "Arandas (Los Altos), Jalisco",
        "bbox": (-102.45, 20.62, -102.25, 20.77),
    },
}

# Nombre de clase (como se escribe en el campo `clase` de las etiquetas) -> código en el mapa.
CLASES = {
    "agave": 1,
    "maiz": 2,
    "cana_de_azucar": 3,
    "sorgo": 4,
    "berries_invernadero": 5,
    "huerta": 6,  # aguacate, limón, otros frutales
    "pastizal": 7,
    "bosque": 8,
    "matorral": 9,
    "urbano": 10,
    "agua": 11,
    "suelo_desnudo": 12,
}

NOMBRE_CLASE = {codigo: nombre for nombre, codigo in CLASES.items()}
