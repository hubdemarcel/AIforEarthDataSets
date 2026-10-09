"""Serie larga de plantación de agave (1993–2026) uniendo Landsat y Sentinel-2.

Landsat (30 m, 1993–2017) se lleva a la escala de Sentinel-2 con la calibración
del periodo en que se traslapan (2018–2021); Sentinel-2 (2018–2026) se promedia a
30 m. Sobre la serie anual de verdor de secas y amplitud se detectan todos los
años de establecimiento de agave de cada pixel (`agave.plantaciones`).

Uso:
    python -m agricultura.serie_historica --resultados agricultura/resultados/tequila
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.enums import Resampling

from . import agave

AMPLITUD_LANDSAT = 1.15  # Landsat TOA subestima la amplitud ~15% frente a Sentinel-2
PRIMER_ANIO_LANDSAT = 1993
PRIMER_ANIO_S2 = 2018


def _abrir(carpeta):
    return xr.open_mfdataset(sorted(carpeta.glob("ndvi_*.nc")), combine="by_coords", decode_coords="all").ndvi.load()


def metricas_combinadas(resultados):
    landsat = _abrir(resultados / "historico_landsat" / "mensual")
    s2 = _abrir(resultados / "historico" / "mensual")
    l_secas, l_amp = agave.metricas_anuales(landsat)
    s_secas, s_amp = agave.metricas_anuales(s2)
    rejilla = landsat.isel(tiempo=0, drop=True)

    def a_30m(da):
        return xr.concat(
            [da.sel(anio=a).rio.write_crs(s2.rio.crs).rio.reproject_match(rejilla, resampling=Resampling.average)
             for a in da.anio.values], "anio").assign_coords(anio=da.anio.values)

    anios_l = [a for a in l_secas.anio.values if PRIMER_ANIO_LANDSAT <= a < PRIMER_ANIO_S2]
    secas = xr.concat([l_secas.sel(anio=anios_l), a_30m(s_secas)], "anio")
    amp = xr.concat([l_amp.sel(anio=anios_l) * AMPLITUD_LANDSAT, a_30m(s_amp)], "anio")
    return secas, amp, rejilla


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resultados", type=Path, required=True)
    args = p.parse_args(argv)
    salida = args.resultados / "serie_historica"
    salida.mkdir(exist_ok=True)

    secas, amp, rejilla = metricas_combinadas(args.resultados)
    anios = secas.anio.values
    n_anios = len(anios)
    S = secas.values.reshape(n_anios, -1)
    A = amp.values.reshape(n_anios, -1)
    evento = agave.plantaciones(S, A)

    ha_pixel = 0.09  # 30 m x 30 m
    plantado = pd.Series(evento.sum(1) * ha_pixel, index=anios, name="hectareas_plantadas").round(0)
    # Los últimos años no tienen suficientes años posteriores para confirmar la plantación
    confirmable = anios <= anios.max() - 2
    tabla = pd.DataFrame({"hectareas_plantadas": plantado, "confirmable": confirmable})
    tabla.index.name = "anio"
    tabla.to_csv(salida / "plantacion_por_anio.csv")

    ultimo = np.where(evento.any(0), n_anios - 1 - evento[::-1].argmax(0), -1)
    anio_ultimo = np.where(ultimo >= 0, anios[np.clip(ultimo, 0, None)], 0).reshape(rejilla.shape).astype("uint16")
    capa = rejilla.copy(data=anio_ultimo)
    capa.encoding = {}
    capa.rio.write_nodata(0).rio.to_raster(salida / "ultima_plantacion.tif")
    np.save(salida / "eventos.npy", evento.reshape(n_anios, *rejilla.shape))
    json.dump({"anios": anios.tolist()}, open(salida / "anios.json", "w"))
    print(tabla.to_string())


if __name__ == "__main__":
    main()
