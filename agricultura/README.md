# Detección de cultivos con Sentinel-2 (piloto: agave en Jalisco)

Mapa de qué se sembró en cada predio a partir de imágenes satelitales Sentinel-2
de los **12 meses completos más recientes**. Primer objetivo: separar el agave de
los demás cultivos y coberturas, para después estudiar el agave a detalle
(edad de plantación, salud, superficie por municipio).

## Cómo funciona

1. **Imágenes.** Sentinel-2 L2A (10 m por pixel, una pasada cada ~5 días) desde
   el bucket público de AWS (`sentinel-cogs`). Solo se lee el recorte de la zona.
   Se quitan las nubes con la capa SCL y cada mes se resume en una mediana.
2. **Elevación.** Copernicus DEM 30 m (AWS `copernicus-dem-30m`): altitud y pendiente.
3. **Características por pixel.** Verdor (NDVI), clorofila (NDRE), humedad (NDMI)
   y suelo desnudo (BSI) de cada mes, más estadísticas anuales y las bandas en
   secas y en lluvias. El calendario de verdor distingue cultivos: el agave se
   mantiene casi constante todo el año y el maíz de temporal sube en julio–septiembre.
4. **Sin etiquetas:** agrupamiento (k-means) de pixeles con calendario parecido.
   Sirve para ver los patrones reales de la zona y decidir dónde etiquetar.
5. **Con etiquetas:** Random Forest entrenado con predios conocidos, validado con
   predios que el modelo no vio. Produce el mapa de cultivos y la superficie por cultivo.

## Uso

```bash
pip install -r agricultura/requirements.txt

# Patrones sin etiquetas (últimos 12 meses completos)
python -m agricultura.pipeline --zona tequila --salida agricultura/resultados/tequila

# Mapa de cultivos con predios etiquetados
python -m agricultura.pipeline --zona tequila --etiquetas predios.geojson \
    --salida agricultura/resultados/tequila
```

- `--zona`: `tequila` (Tequila–Amatitán) o `los_altos` (Arandas); o `--bbox LON_MIN LAT_MIN LON_MAX LAT_MAX`.
- `--hasta AAAA-MM`: fija el último mes (por omisión, el último mes completo).
- Las imágenes descargadas se guardan en la carpeta de salida y se reutilizan.

### Resultados

| Archivo | Contenido |
|---|---|
| `color_verdadero.jpg/.tif` | Imagen en color de la temporada seca (para revisar y etiquetar en QGIS) |
| `grupos.png/.tif`, `grupos_ndvi_mensual.csv` | Patrones sin etiquetas y su curva de verdor |
| `cultivos.tif`, `probabilidad.tif` | Mapa de cultivos y confianza del modelo |
| `superficie.csv` | Hectáreas por cultivo |
| `reporte.txt` | Precisión por cultivo, matriz de confusión, características más importantes |

## Etiquetas (predios conocidos)

GeoJSON (o GPKG/SHP) de polígonos o puntos con un campo `clase`. Clases válidas
(en `config.py`): `agave`, `maiz`, `cana_de_azucar`, `sorgo`,
`berries_invernadero`, `huerta`, `pastizal`, `bosque`, `matorral`, `urbano`,
`agua`, `suelo_desnudo`. Ver `ejemplos/etiquetas_formato.geojson`.

Recomendado: 30+ predios por clase, repartidos en toda la zona, de agave de distintas
edades. Pueden marcarse en QGIS sobre `color_verdadero.tif` y con conocimiento de campo.

## Limitaciones

- Plantaciones de agave de menos de 1–2 años se confunden con suelo desnudo.
- Predios menores a ~0.5 ha tienen pocos pixeles.
- En lluvias (junio–septiembre) hay meses con muchas nubes; los huecos se rellenan
  interpolando entre meses.
