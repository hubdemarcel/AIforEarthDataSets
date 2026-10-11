"""Mantenimiento del agave por año: limpio, regular o enmontado.

Un agave limpio (deshierbado) casi no reverdece en lluvias: su amplitud (lluvias - secas)
es baja. Cuando no se mantiene, la maleza entre hileras crece en lluvias y la amplitud
sube hasta parecerse a un pastizal. Para cada pixel de agave en pie y cada año desde el
2.º después de plantar (el 1.º suele llevar maíz intercalado o maleza):

- limpio: amplitud < 0.20
- regular: 0.20 a 0.30
- enmontado: ≥ 0.30

Umbrales tomados de los 9 agaves confirmados en Tequila–Amatitán (amplitud después de
plantar de 0.09 a 0.38, mediana 0.21); 0.30 es el mismo corte de la confianza alta.
Como un año muy lluvioso sube la amplitud de todo, la tabla incluye también la amplitud
mediana de los campos de cultivo anual del mismo año para comparar.

Guarda por mosaico `agave_mantenimiento.tif` (una banda por año: 0 no aplica, 1 limpio,
2 regular, 3 enmontado) y la tabla por municipio y año.

Uso:
    python -m agricultura.mantenimiento --mosaicos agricultura/resultados/mosaicos \
        --salida agricultura/resultados/municipios
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rioxarray
from rasterio.features import rasterize

from .municipios import MUNICIPIOS, _area_propia

AGAVE, CULTIVO_ANUAL = 4, 6
LIMPIO_MAX, REGULAR_MAX = 0.20, 0.30
NIVELES = {1: "limpio", 2: "regular", 3: "enmontado"}
SIN_DATO = -32768


def niveles(amp, est, anios, agave):
    """Nivel por año (años, alto, ancho) en uint8. amp en int16 x10000."""
    salida = np.zeros(amp.shape, "uint8")
    for i, anio in enumerate(anios):
        a = amp[i]
        aplica = agave & (anio >= est + 2) & (a != SIN_DATO)
        salida[i] = np.where(aplica, np.where(a < LIMPIO_MAX * 10000, 1,
                                              np.where(a < REGULAR_MAX * 10000, 2, 3)), 0)
    return salida


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaicos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    partes, referencia = [], []
    for m in sorted(c for c in args.mosaicos.iterdir() if (c / "metricas_anuales.npz").exists()):
        uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
        est = rioxarray.open_rasterio(m / "agave_establecimiento.tif").squeeze("band", drop=True).values.astype("int32")
        z = np.load(m / "metricas_anuales.npz")
        anios, amp = z["anios"], z["amplitud"]
        clase = uso.values
        nivel = niveles(amp, est, anios, clase == AGAVE)

        perfil = {"driver": "GTiff", "height": clase.shape[0], "width": clase.shape[1], "count": len(anios),
                  "dtype": "uint8", "crs": uso.rio.crs, "transform": uso.rio.transform(), "nodata": 0,
                  "compress": "deflate"}
        with rasterio.open(m / "agave_mantenimiento.tif", "w", **perfil) as dst:
            dst.write(nivel)
            dst.descriptions = tuple(str(a) for a in anios)

        ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=clase.shape,
                        transform=uso.rio.transform(), fill=0, dtype="int32")
        propio = _area_propia(uso) & (ids > 0)
        ha = abs(np.prod(uso.rio.resolution())) / 10_000
        cultivo = propio & (clase == CULTIVO_ANUAL)
        for i, anio in enumerate(anios):
            sel = propio & (nivel[i] > 0)
            d = pd.DataFrame({"mun": ids[sel] - 1, "nivel": nivel[i][sel], "amp": amp[i][sel] / 10000})
            g = d.groupby(["mun", "nivel"]).amp.agg(["size", "sum"]).reset_index()
            partes.append(g.assign(anio=int(anio), ha=g["size"] * ha))
            ref = amp[i][cultivo]
            ref = ref[ref != SIN_DATO]
            referencia.append({"mosaico": m.name, "anio": int(anio), "pixeles": ref.size,
                               "amp_cultivo_anual": float(np.median(ref)) / 10000 if ref.size else np.nan})
        print(f"{m.name}: listo", flush=True)
        del amp, nivel

    df = pd.concat(partes)
    suma = df.groupby(["mun", "anio"])[["size", "sum"]].sum()
    ha_tabla = df.groupby(["mun", "anio", "nivel"]).ha.sum().unstack(fill_value=0).rename(columns=NIVELES)
    ha_tabla.columns = [f"{c}_ha" for c in ha_tabla.columns]
    total = ha_tabla.sum(1)
    ha_tabla["pct_enmontado"] = (100 * ha_tabla.get("enmontado_ha", 0) / total).round(1)
    ha_tabla = ha_tabla.round(0)
    ha_tabla["amp_media_agave"] = (suma["sum"] / suma["size"]).round(3)
    ha_tabla = ha_tabla.reset_index()
    ha_tabla = mun[["municipio", "estado", "denominacion_origen"]].join(ha_tabla.set_index("mun"), how="inner")
    ha_tabla.sort_values(["estado", "municipio", "anio"]).to_csv(
        args.salida / "agave_mantenimiento_por_municipio.csv", index=False)

    ref = pd.DataFrame(referencia)
    pesos = ref.pixeles.where(ref.pixeles > 0)
    anual = ref.assign(p=ref.amp_cultivo_anual * pesos).groupby("anio")[["p", "pixeles"]].sum()
    anual = pd.DataFrame({"amp_cultivo_anual": (anual.p / anual.pixeles).round(3)})
    por_anio = df.groupby(["anio", "nivel"]).ha.sum().unstack(fill_value=0).rename(columns=NIVELES).round(0)
    por_anio["pct_enmontado"] = (100 * por_anio.get("enmontado", 0) / por_anio.sum(1)).round(1)
    s = df.groupby("anio")[["size", "sum"]].sum()
    por_anio["amp_media_agave"] = (s["sum"] / s["size"]).round(3)
    por_anio = por_anio.join(anual)
    por_anio.to_csv(args.salida / "agave_mantenimiento_total.csv")
    print(por_anio.to_string())


if __name__ == "__main__":
    main()
