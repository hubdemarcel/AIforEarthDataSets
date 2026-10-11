# Usos de la información satelital de agave

Qué se puede hacer con lo que ya produce el proyecto: uso de suelo, año de plantación,
jima, confianza, mantenimiento, origen de las plantaciones, curva de crecimiento y la
muestra de respaldo, todo por pixel de 20 m y resumido por municipio.

## Ya disponible

| Producto | Archivo | Qué responde |
|---|---|---|
| Agave en pie por municipio | `resultados/municipios/agave_por_municipio_y_anio.csv` | Cuánto agave hay y en qué año se plantó |
| Confianza | `resultados/municipios/agave_por_confianza.csv`, `mosaicos/*/agave_confianza.tif` | Qué tan seguro es que sea agave y no pastizal |
| Jima | `resultados/municipios/jima_por_municipio.csv`, `mosaicos/*/agave_jima.tif` | Dónde y cuándo se cosechó |
| Mantenimiento | `resultados/municipios/agave_mantenimiento_por_municipio.csv`, `mosaicos/*/agave_mantenimiento.tif` | Agave limpio, regular o enmontado por año |
| Origen de plantaciones | `resultados/municipios/origen_plantaciones_por_municipio.csv` | Si el agave nuevo salió de maíz, pastizal, monte o replantación |
| Curva de crecimiento | `resultados/municipios/crecimiento_agave_por_municipio.csv` | Verdor de secas según la edad, por municipio |
| Muestra de respaldo | `resultados/muestra/*.npz` | Serie 2018–2026 de pixeles para probar reglas y modelos sin bajar imágenes |

## Usos

### 1. Oferta futura de agave maduro (prioridad)
Con el inventario por edad se calcula cuántas hectáreas llegan a talla de jima (6–7 años)
cada año, por municipio, y con el rendimiento del SIAP cuántas toneladas. El boom de
plantación de 2021–2023 se traduce en una ola de agave maduro hacia 2028–2030. Es el dato
de oferta que el mercado no tiene y la base para retomar el modelo de precios.

### 2. Edad a la jima como señal de mercado
Si en un año se jima agave de 4 años en lugar de 6–7, hay escasez y precio alto; si la
jima espera a agave de 8+ años o hay mucho agave maduro sin jimar, hay sobreoferta. Sale
de cruzar el año de plantación con el año de jima.

### 3. Verificación de proveedores (tequileras y compradores)
Para un predio que vende agave: superficie real, edad, si ya se jimó, estado de
mantenimiento y si se plantó sobre monte. Apoya las compras y los compromisos de agave sin
deforestación.

### 4. Encontrar agave disponible para compra
Agave maduro y enmontado suele ser de productores que no lo están cuidando y pueden estar
dispuestos a vender. Mapa por municipio de agave de 6+ años con mantenimiento bajo.

### 5. Crédito y seguro agrícola
Valuar una plantación como garantía según edad y estado; detectar daños o rezago por
sequía con la curva de crecimiento (plantaciones muy por debajo de la mediana de su edad).

### 6. Riesgo climático
Comparar el crecimiento por municipio en años secos contra lluviosos para saber qué
zonas resisten mejor la sequía y dónde conviene plantar.

## Pendientes para que estos usos sean confiables
- Terminar la cobertura de los 181 municipios de la DO.
- Ajustar la confusión con pastizal usando las verificaciones de campo.
- Filtro de zonas urbanas (al final).
- En el origen de plantaciones, separar selva de riego intensivo del Bajío con la pendiente del terreno.
