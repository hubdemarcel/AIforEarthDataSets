"""Convierte los compuestos mensuales en características por pixel para el clasificador.

La idea clave: cada cultivo tiene un "calendario" de verdor distinto. El maíz de
temporal sube en julio–septiembre y cae en secas; el agave se mantiene casi
constante todo el año; la caña es verde casi todo el año pero con cortes.
"""

import numpy as np
import xarray as xr

INDICES_MENSUALES = ["ndvi", "ndre", "ndmi", "bsi"]
SECAS = [3, 4, 5]
LLUVIAS = [8, 9, 10]


def _normalizada(a, b):
    return (a - b) / (a + b)


def indices(s2):
    """Índices espectrales a partir de reflectancias Sentinel-2 (0–1)."""
    return xr.Dataset(
        {
            # Verdor general
            "ndvi": _normalizada(s2.B08, s2.B04),
            # Borde rojo: sensible a clorofila, separa cultivos con NDVI parecido
            "ndre": _normalizada(s2.B8A, s2.B05),
            # Humedad de la vegetación
            "ndmi": _normalizada(s2.B08, s2.B11),
            # Suelo desnudo (alto en predios recién preparados o entre hileras)
            "bsi": _normalizada(s2.B11 + s2.B04, s2.B08 + s2.B02),
            # Agua
            "ndwi": _normalizada(s2.B03, s2.B08),
        }
    )


def rellenar_huecos(da, dim="mes"):
    """Rellena meses sin dato (nubes) interpolando en el tiempo; los extremos con el vecino."""
    lineal = da.interpolate_na(dim, method="linear")
    return lineal.bfill(dim).ffill(dim)


def construir(s2, dem=None):
    """Pila de características (caracteristica, y, x) float32.

    `s2`: Dataset mensual de bandas (mes, y, x). `dem`: Dataset con `elevacion` y `pendiente`.
    """
    capas = {}
    idx = indices(s2)

    for nombre in INDICES_MENSUALES:
        serie = rellenar_huecos(idx[nombre])
        for mes in serie.mes.values:
            capas[f"{nombre}_m{int(mes):02d}"] = serie.sel(mes=mes)
        capas[f"{nombre}_media"] = serie.mean("mes")
        capas[f"{nombre}_std"] = serie.std("mes")
        capas[f"{nombre}_min"] = serie.min("mes")
        capas[f"{nombre}_max"] = serie.max("mes")
        capas[f"{nombre}_amplitud"] = serie.quantile(0.9, "mes").drop_vars("quantile") - serie.quantile(
            0.1, "mes"
        ).drop_vars("quantile")

    ndvi = rellenar_huecos(idx.ndvi)
    capas["ndvi_mes_pico"] = (ndvi.fillna(-1).argmax("mes") + 1).astype("float32").where(ndvi.notnull().any("mes"))
    capas["meses_verdes"] = (ndvi > 0.5).sum("mes").astype("float32")
    capas["ndwi_media"] = idx.ndwi.mean("mes")

    for banda in s2.data_vars:
        capas[f"{banda}_anual"] = s2[banda].median("mes")
        capas[f"{banda}_secas"] = s2[banda].sel(mes=SECAS).median("mes")
        capas[f"{banda}_lluvias"] = s2[banda].sel(mes=LLUVIAS).median("mes")

    if dem is not None:
        capas["elevacion"] = dem.elevacion
        capas["pendiente"] = dem.pendiente

    pila = xr.concat(
        [da.drop_vars([c for c in da.coords if c not in ("y", "x", "spatial_ref")]) for da in capas.values()],
        dim="caracteristica",
    )
    pila = pila.assign_coords(caracteristica=list(capas))
    return pila.astype("float32").transpose("caracteristica", "y", "x")
