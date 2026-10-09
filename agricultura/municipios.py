"""Resume los mosaicos procesados por municipio.

Cada mosaico de Sentinel-2 mide 109.8 km y se encima ~9.8 km con sus vecinos al
este y al sur. Para no contar dos veces, cada pixel se asigna solo al mosaico
"dueño" de su cuadro MGRS de 100 km (los primeros 100 km desde la esquina
noroeste del mosaico). Para cada municipio se reporta la superficie por uso del
suelo, el agave en pie por año de establecimiento y qué fracción del municipio ya
está cubierta por mosaicos procesados.

Uso:
    python -m agricultura.municipios --mosaicos agricultura/resultados/mosaicos \
        --salida agricultura/resultados/municipios
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
from rasterio.features import rasterize

from .agave import CLASES

MUNICIPIOS = Path(__file__).parent / "datos_externos" / "municipios_estados_do.geojson"
LADO_PROPIO = 100_000  # metros del cuadro MGRS propio de cada mosaico
AGAVE, COSECHADO = 4, 5


def _area_propia(capa):
    """Máscara de los pixeles dentro del cuadro de 100 km propio del mosaico."""
    x, y = capa.x.values, capa.y.values
    res_x, res_y = capa.rio.resolution()
    x0 = x[0] - res_x / 2
    y_top = y[0] - res_y / 2  # res_y es negativo
    return (y[:, None] > y_top - LADO_PROPIO) & (x[None, :] < x0 + LADO_PROPIO)


def resumir_mosaico(carpeta, municipios):
    """Pixeles por municipio, clase y año en un mosaico. Devuelve tres DataFrames de conteos."""
    uso = rioxarray.open_rasterio(carpeta / "uso_suelo.tif").squeeze("band", drop=True)
    est = rioxarray.open_rasterio(carpeta / "agave_establecimiento.tif").squeeze("band", drop=True).values
    jima = rioxarray.open_rasterio(carpeta / "agave_jima.tif").squeeze("band", drop=True).values
    mun = municipios.to_crs(uso.rio.crs)
    ids = rasterize(zip(mun.geometry, mun.index + 1), out_shape=uso.shape, transform=uso.rio.transform(),
                    fill=0, dtype="int32")
    propio = _area_propia(uso)
    clase = uso.values
    m = propio & (ids > 0) & (clase > 0)
    ha_pixel = abs(np.prod(uso.rio.resolution())) / 10_000

    df = pd.DataFrame({"mun": ids[m] - 1, "clase": clase[m], "est": est[m], "jima": jima[m]})
    por_clase = df.groupby(["mun", "clase"]).size().mul(ha_pixel).rename("hectareas")
    agave = df[df.clase == AGAVE].groupby(["mun", "est"]).size().mul(ha_pixel).rename("hectareas")
    jimas = df[df.clase == COSECHADO].groupby(["mun", "jima"]).size().mul(ha_pixel).rename("hectareas")
    cubierto = pd.Series(np.bincount(ids[propio & (ids > 0)] - 1, minlength=len(mun)) * ha_pixel)
    return por_clase, agave, jimas, cubierto


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaicos", type=Path, required=True, help="carpeta con una subcarpeta por mosaico")
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)

    municipios = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    area_ha = municipios.to_crs("EPSG:6372").area / 10_000  # INEGI Lambert, área igual
    carpetas = sorted(c for c in args.mosaicos.iterdir() if (c / "uso_suelo.tif").exists())
    print(f"Mosaicos procesados: {[c.name for c in carpetas]}")

    partes = [resumir_mosaico(c, municipios) for c in carpetas]
    por_clase = pd.concat([x[0] for x in partes]).groupby(level=[0, 1]).sum()
    agave = pd.concat([x[1] for x in partes]).groupby(level=[0, 1]).sum()
    jimas = pd.concat([x[2] for x in partes]).groupby(level=[0, 1]).sum()
    cubierto = sum(x[3] for x in partes)

    base = municipios[["municipio", "estado", "denominacion_origen"]].copy()
    base["area_ha"] = area_ha.round(0)
    base["cobertura_pct"] = (100 * cubierto / area_ha).clip(upper=100).round(1)
    usos = por_clase.unstack(fill_value=0).rename(columns=CLASES).round(0)
    tabla = base.join(usos, how="inner")
    tabla = tabla[tabla.cobertura_pct > 0].sort_values(CLASES[AGAVE], ascending=False)
    tabla.to_csv(args.salida / "uso_suelo_por_municipio.csv", index=False)

    agave_anio = agave.unstack(fill_value=0).round(0)
    agave_anio.columns = [f"plantado_{c}" for c in agave_anio.columns]
    agave_tabla = base.join(agave_anio, how="inner")
    agave_tabla.insert(4, "agave_en_pie_ha", agave_anio.sum(1).round(0))
    agave_tabla = agave_tabla.sort_values("agave_en_pie_ha", ascending=False)
    agave_tabla.to_csv(args.salida / "agave_por_municipio_y_anio.csv", index=False)

    jima_anio = jimas.unstack(fill_value=0).round(0)
    jima_anio.columns = [f"jima_{c}" for c in jima_anio.columns]
    base.join(jima_anio, how="inner").to_csv(args.salida / "jima_por_municipio.csv", index=False)

    print(agave_tabla.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
