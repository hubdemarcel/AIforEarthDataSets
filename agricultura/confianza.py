"""Confianza de cada pixel clasificado como agave en pie, según qué tan limpia es su firma.

Después de plantar, el agave sube su verdor de secas año con año y casi no tiene
pico de lluvias. Un pastizal o matorral que imita el patrón conserva un pico de
lluvias alto. El primer año después de plantar se ignora porque es común
intercalar maíz o tener maleza.

- alta: amplitud media (desde el 2.º año tras plantar) < 0.30 y verdor de secas del último año ≥ 0.28
- media: amplitud media < 0.40

Umbrales tomados de los 9 agaves confirmados en Tequila–Amatitán: su amplitud media después de
plantar va de 0.09 a 0.38 (mediana 0.21) y su verdor de secas en 2026 de 0.29 a 0.43.
- baja: el resto (se clasificó como agave, pero con firma parecida a pastizal o matorral)

Uso:
    python -m agricultura.confianza --mosaicos agricultura/resultados/mosaicos \
        --salida agricultura/resultados/municipios
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
from rasterio.features import rasterize

from .municipios import MUNICIPIOS, _area_propia

AGAVE = 4
NIVELES = {1: "baja", 2: "media", 3: "alta"}
AMP_ALTA, AMP_MEDIA, SECAS_ALTA = 0.30, 0.40, 0.28


def confianza(secas, amp, est, anios, filas=500):
    """Nivel 1–3 para pixeles de agave (est > 0), 0 en el resto.

    secas/amp: (años, alto, ancho), NDVI x10000 en int16 con -32768 como sin dato (se convierte por bloques).
    """
    _, alto, ancho = secas.shape
    nivel = np.zeros((alto, ancho), "uint8")
    anios = np.asarray(anios)[:, None, None]
    for f in range(0, alto, filas):
        b = slice(f, f + filas)
        e = est[b][None]
        sb = secas[:, b].astype("float32")
        ab = amp[:, b].astype("float32")
        sb[sb == -32768] = np.nan
        ab[ab == -32768] = np.nan
        sb /= 10000
        ab /= 10000
        hay = e > 0
        post = (anios >= e + 2) & hay  # desde el 2.º año después de plantar
        with np.errstate(all="ignore"):
            amp_post = np.nanmean(np.where(post, ab, np.nan), 0)
            ultimo = sb[-1]
        n = post.sum(0)
        alta = (amp_post < AMP_ALTA) & (ultimo >= SECAS_ALTA)
        media = amp_post < AMP_MEDIA
        lv = np.where(alta, 3, np.where(media, 2, 1))
        lv = np.where(n == 0, 2, lv)  # plantado muy reciente: sin años suficientes para juzgar
        nivel[b] = np.where(hay[0], lv, 0)
    return nivel


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaicos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    partes = []
    for m in sorted(c for c in args.mosaicos.iterdir() if (c / "metricas_anuales.npz").exists()):
        uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
        est = rioxarray.open_rasterio(m / "agave_establecimiento.tif").squeeze("band", drop=True).values.astype(int)
        est[uso.values != AGAVE] = 0
        z = np.load(m / "metricas_anuales.npz")
        secas, amp = z["secas"], z["amplitud"]
        nivel = confianza(secas, amp, est, z["anios"])
        del secas, amp
        capa = uso.copy(data=nivel)
        capa.encoding = {}
        capa.rio.write_nodata(0).rio.to_raster(m / "agave_confianza.tif", compress="deflate")

        ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=uso.shape,
                        transform=uso.rio.transform(), fill=0, dtype="int32")
        sel = _area_propia(uso) & (ids > 0) & (nivel > 0)
        ha = abs(np.prod(uso.rio.resolution())) / 10_000
        partes.append(pd.DataFrame({"mun": ids[sel] - 1, "nivel": nivel[sel]}).groupby(["mun", "nivel"]).size() * ha)
        print(f"{m.name}: " + ", ".join(f"{NIVELES[k]} {v * ha:,.0f} ha" for k, v in
                                        zip(*np.unique(nivel[nivel > 0], return_counts=True))), flush=True)

    tabla = pd.concat(partes).groupby(level=[0, 1]).sum().unstack(fill_value=0).rename(columns=NIVELES).round(0)
    tabla = mun[["municipio", "estado"]].join(tabla, how="inner")
    tabla["conservador_alta"] = tabla.get("alta", 0)
    tabla["intermedio_alta_media"] = tabla.get("alta", 0) + tabla.get("media", 0)
    tabla["amplio_todo"] = tabla.intermedio_alta_media + tabla.get("baja", 0)
    tabla.sort_values("amplio_todo", ascending=False).to_csv(args.salida / "agave_por_confianza.csv", index=False)
    print(tabla.sort_values("amplio_todo", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
