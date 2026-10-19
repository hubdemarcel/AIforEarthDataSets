# Agave en pie: paquete para agaves.pro

Datos listos para la página de agave en pie de Agaves Pro v2. Salen del análisis
satelital de este repositorio: Sentinel-2 de 2018 a 2026 y Landsat de 2009 a 2017, sobre
los 35 mosaicos de la DO del tequila. Se regeneran con
`python -m agricultura.exportar_agaves_pro`.

**Antes de mostrarlo al público:** las hectáreas satelitales salen muy por encima del
SIAP. Las fuentes de error conocidas son la sierra del norte de Jalisco y Nayarit, el
aguacate en Michoacán y el sur de Jalisco, y Tamaulipas, donde las reglas no están
calibradas. Por ahora sirven para ver tendencias y comparar municipios, no para dar
totales. Tamaulipas lleva `calibrado = false` y queda fuera de los totales.

## Archivos

| Archivo | Qué tiene |
|---|---|
| `agave_en_pie_municipios.geojson` | 347 municipios de los cinco estados con su geometría (simplificada, WGS84) y las mismas columnas que el CSV. Es la base del mapa. |
| `agave_en_pie_municipios.csv` | Una fila por municipio, sin geometría. |
| `resumen.json` | Totales para las tarjetas y las gráficas: jima por año, lo que sigue en pie por año de plantación y totales por estado. |
| `agave_viejo_cohortes.csv` | Detalle: hectáreas por municipio, año de plantación (2009–2017) y año de jima (`0` = sigue en pie en 2026). |
| `oferta_agave_viejo_*.csv` | Agave viejo en pie por año de 2024 a 2031, en hectáreas y toneladas. `maximo = True` marca los años sin observación de jima, que son un máximo. |
| `oferta_agave_maduro_*.csv` | Agave joven (plantado 2018–2024) que cumple 5, 6 y 7 años cada año, por nivel de confianza. |
| `demo_agave_en_pie.html` | Página demo autocontenida: tarjetas, dos gráficas, mapa por municipio y tabla. Se abre directo en el navegador. |

## Columnas de `agave_en_pie_municipios`

| Columna | Significado |
|---|---|
| `municipio`, `estado` | Nombre (geoBoundaries) |
| `id_geoboundaries`, `cvegeo_inegi` | Claves para cruzar con otras tablas (`cvegeo_inegi` solo en municipios de la DO) |
| `denominacion_origen` | `si` / `no`: si el municipio está en la DO del tequila |
| `viejo_en_pie_ha` | Agave plantado de 2009 a 2017 que sigue sin jimar en 2026 |
| `joven_en_pie_ha` | Agave plantado de 2018 a 2024 en pie |
| `siap_sembrada_2025_ha` | Superficie sembrada de agave según el SIAP 2025 (referencia) |
| `calibrado` | `false` en Tamaulipas |

## Cómo se define "jima"

Una plantación cuenta como jimada cuando el verdor de secas (NDVI mediano de marzo a
mayo) baja de 0.25 a partir del segundo año de plantada. Lo que nunca baja sigue en
pie. Después de 2026 no hay observaciones, así que lo que sigue en pie es un máximo.
