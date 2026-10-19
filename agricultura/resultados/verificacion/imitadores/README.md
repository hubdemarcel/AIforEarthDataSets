# Agave contra sus imitadores: firma espectral (abril y septiembre 2025)

Pixeles que el satélite marca como agave joven (clase 4 de `uso_suelo.tif`) en tres zonas, con las 10 bandas de
Sentinel-2 leídas por `espectral.py`:

- `agave_seguro` (32 puntos): Tequila, Amatitán, Arandas, Tepatitlán.
- `aguacate` (28): Tancítaro, Uruapan, Peribán, Los Reyes, donde el satélite ve mucho más agave que el SIAP.
- `sierra` (7): Del Nayar, Mezquitic, Bolaños. Casi no hay predios compactos de "agave" ahí, solo pixeles sueltos.

Ninguno está verificado en campo; los grupos salen de la geografía. Las columnas `google_maps` de `puntos.csv` sirven
para revisarlos a mano.

## Lo que separa

El infrarrojo de onda corta en secas. La penca suculenta guarda agua y en abril el agave tiene B11 bajo y humedad de
hoja (NDMI = (B08 − B11) / (B08 + B11)) alta; los imitadores están secos:

| abril 2025 | agave seguro | zona de aguacate | sierra |
|---|---|---|---|
| B11 (mediana) | 0.200 | 0.281 | 0.308 |
| NDMI | 0.138 | 0.001 | −0.064 |
| B12/B11 | 0.786 | 0.698 | 0.673 |

Con NDMI de abril > 0.03 se conserva el 97 % del agave seguro y se descarta el 54 % de los puntos de la zona de
aguacate y el 57 % de la sierra. No alcanza solo: Peribán y Tancítaro (huertas probablemente regadas) tienen NDMI
alto como el agave; ahí ayudan el azul/rojo de septiembre (0.72 agave contra 0.90) y el borde rojo.

El NDVI (lo único que usan las reglas actuales) casi no separa los grupos.

## Para usarlo en las reglas

Los mosaicos solo bajaron rojo e infrarrojo cercano. Agregar B11 de un mes de secas por año (20 m) cuesta cerca de
una séptima parte de la descarga original de Sentinel-2 por mosaico.
