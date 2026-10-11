"""Análisis que necesitan las métricas anuales por pixel (`metricas_anuales.npz`) de cada mosaico.

Se corre antes de borrar esas métricas (pesan ~560 MB por mosaico) para conservar lo útil:

1. Muestra de respaldo: 0.5 % de los pixeles del cuadro propio y 5 % de los de agave, con
   su serie anual completa (verdor de secas y amplitud), clase, año de plantación, jima,
   confianza y municipio. Sirve para entrenar y probar reglas o modelos sin volver a bajar
   imágenes (`resultados/muestra/<mosaico>.npz`).
2. Qué había antes de cada plantación (2020 en adelante, con al menos dos años previos):
   bosque denso, selva o vegetación caducifolia, cultivo anual, pastizal/matorral o agave
   anterior (replantación), según la mediana de los años anteriores al año de plantación.
3. Curva de crecimiento: verdor de secas del agave según su edad (años desde la plantación),
   por municipio, para ver qué tan rápido crecen y detectar plantaciones rezagadas.

Uso:
    python -m agricultura.analisis_metricas --mosaicos agricultura/resultados/mosaicos \
        --salida agricultura/resultados
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
from pyproj import Transformer
from rasterio.features import rasterize

from . import agave
from .municipios import MUNICIPIOS, _area_propia

AGAVE, COSECHADO = 4, 5
SIN_DATO = -32768
FRACCION_GENERAL, FRACCION_AGAVE = 0.005, 0.05
ORIGENES = {1: "bosque denso", 2: "selva / caducifolia", 3: "cultivo anual", 4: "pastizal / matorral",
            5: "agave anterior (replantación)"}
AMP_AGAVE_PREVIO = 0.25  # amplitud baja con verdor de secas alto: había agave establecido


def _capa(m, nombre):
    return rioxarray.open_rasterio(m / nombre).squeeze("band", drop=True)


def muestra(m, destino, uso, clase, est, jima, conf, ids, propio, z, semilla):
    """Muestra estratificada de pixeles con su serie anual completa."""
    rng = np.random.default_rng(semilla)
    general = propio & (rng.random(clase.shape) < FRACCION_GENERAL)
    del_agave = propio & np.isin(clase, (AGAVE, COSECHADO)) & (rng.random(clase.shape) < FRACCION_AGAVE)
    filas, cols = np.nonzero(general | del_agave)
    x, y = uso.x.values[cols], uso.y.values[filas]
    lon, lat = Transformer.from_crs(uso.rio.crs, 4326, always_xy=True).transform(x, y)
    np.savez_compressed(
        destino / f"{m.name}.npz",
        anios=z["anios"], lon=lon.astype("float32"), lat=lat.astype("float32"),
        municipio=(ids[filas, cols] - 1).astype("int16"), clase=clase[filas, cols],
        establecimiento=est[filas, cols].astype("int16"), jima=jima[filas, cols].astype("int16"),
        confianza=conf[filas, cols], de_agave=del_agave[filas, cols],
        secas=z["secas"][:, filas, cols].T, amplitud=z["amplitud"][:, filas, cols].T)
    return len(filas)


def origen(secas, amp, est, anios, agave_px):
    """Cobertura previa (1–4) de los pixeles de agave plantados con ≥2 años previos; 0 en el resto."""
    salida = np.zeros(est.shape, "uint8")
    for e in np.unique(est[agave_px]):
        previos = [i for i, a in enumerate(anios) if a < e]
        if len(previos) < 2:
            continue
        sel = agave_px & (est == e)
        s = secas[:, sel][previos].astype("float32")
        a = amp[:, sel][previos].astype("float32")
        s[s == SIN_DATO] = np.nan
        a[a == SIN_DATO] = np.nan
        with np.errstate(all="ignore"):
            s, a = np.nanmedian(s, 0) / 10000, np.nanmedian(a, 0) / 10000
        o = np.where(s >= agave.BOSQUE, 1,
                     np.where(a >= agave.AMPLITUD_ANUAL, np.where(s < agave.SECAS_ESTABLECIDO, 3, 2),
                              np.where((a < AMP_AGAVE_PREVIO) & (s >= agave.SECAS_ESTABLECIDO), 5, 4)))
        o[~np.isfinite(s) | ~np.isfinite(a)] = 0
        salida[sel] = o
    return salida


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaicos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True, help="carpeta resultados/")
    args = p.parse_args(argv)
    (args.salida / "muestra").mkdir(parents=True, exist_ok=True)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    origenes, crecimiento = [], []
    for k, m in enumerate(sorted(c for c in args.mosaicos.iterdir() if (c / "metricas_anuales.npz").exists())):
        uso = _capa(m, "uso_suelo.tif")
        clase = uso.values
        est = _capa(m, "agave_establecimiento.tif").values.astype("int32")
        jima = _capa(m, "agave_jima.tif").values
        conf = _capa(m, "agave_confianza.tif").values if (m / "agave_confianza.tif").exists() else np.zeros_like(clase)
        z = np.load(m / "metricas_anuales.npz")
        anios, secas, amp = z["anios"], z["secas"], z["amplitud"]
        ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=clase.shape,
                        transform=uso.rio.transform(), fill=0, dtype="int32")
        propio = _area_propia(uso) & (ids > 0)
        ha = abs(np.prod(uso.rio.resolution())) / 10_000

        n = muestra(m, args.salida / "muestra", uso, clase, est, jima, conf, ids, propio, z, semilla=k)

        agave_px = propio & (clase == AGAVE) & (est > 0)
        o = origen(secas, amp, est, anios, agave_px)
        sel = o > 0
        origenes.append(pd.DataFrame({"mun": ids[sel] - 1, "anio_plantacion": est[sel], "origen": o[sel]})
                        .groupby(["mun", "anio_plantacion", "origen"]).size().mul(ha))

        # Crecimiento: verdor de secas por edad (histograma en pasos de 0.01 para sacar cuantiles al juntar mosaicos)
        for i, anio in enumerate(anios):
            edad = anio - est
            v = agave_px & (edad >= 0) & (secas[i] != SIN_DATO)
            if not v.any():
                continue
            caja = np.clip(np.round(secas[i][v] / 100), -20, 100).astype("int16")
            crecimiento.append(pd.DataFrame({"mun": ids[v] - 1, "edad": edad[v], "caja": caja})
                               .value_counts().rename("pixeles"))
        print(f"{m.name}: muestra {n:,} pixeles, origen {sel.sum() * ha:,.0f} ha", flush=True)
        del secas, amp, z

    nombres = mun[["municipio", "estado", "denominacion_origen"]]
    tabla = pd.concat(origenes).groupby(level=[0, 1, 2]).sum().unstack(fill_value=0).rename(columns=ORIGENES).round(0)
    tabla["pct_desmonte"] = (100 * tabla.get("bosque denso", 0) / tabla.sum(1)).round(1)
    tabla = nombres.join(tabla.reset_index(level=1), how="inner")
    tabla.to_csv(args.salida / "municipios" / "origen_plantaciones_por_municipio.csv", index=False)
    total = tabla.groupby("anio_plantacion")[list(ORIGENES.values())].sum()
    (total.div(total.sum(1), axis=0) * 100).round(1).assign(hectareas=total.sum(1)).to_csv(
        args.salida / "municipios" / "origen_plantaciones_total.csv")
    print(total.round(0).to_string())

    h = pd.concat(crecimiento).groupby(level=[0, 1, 2]).sum().reset_index()

    def cuantiles(g):
        g = g.sort_values("caja")
        acum = g.pixeles.cumsum() / g.pixeles.sum()
        q = lambda f: g.caja.values[np.searchsorted(acum.values, f)] / 100
        return pd.Series({"pixeles": g.pixeles.sum(), "p25": q(0.25), "mediana": q(0.5), "p75": q(0.75)})

    por_mun = h.groupby(["mun", "edad"]).apply(cuantiles, include_groups=False).reset_index()
    por_mun = nombres.join(por_mun.set_index("mun"), how="inner")
    por_mun.to_csv(args.salida / "municipios" / "crecimiento_agave_por_municipio.csv", index=False)
    general = h.groupby("edad").apply(cuantiles, include_groups=False)
    general.to_csv(args.salida / "municipios" / "crecimiento_agave_total.csv")
    print(general.to_string())


if __name__ == "__main__":
    main()
