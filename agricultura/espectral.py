"""Firma espectral completa (10 bandas de Sentinel-2) en puntos, para separar agave de lo que lo imita.

El NDVI usa dos bandas. El agave tiene rasgos que se ven en otras: penca azul-grisácea
(azul y borde rojo), hoja suculenta con mucha agua (infrarrojo de onda corta) y suelo
visible entre hileras. Este módulo lee, para cada punto, la reflectancia mediana sin
nubes de cada banda en un mes dado, leyendo solo una ventana chica (3x3 pixeles de 10 m).

Uso:
    python -m agricultura.espectral --puntos puntos.csv --meses 2026-04 2026-05 2025-09 --salida espectro.csv
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

from . import datos

BANDAS = datos.ASSETS_S2  # asset -> banda


def _leer_punto(href, x, y, tam=3):
    with rasterio.open(href) as src:
        fila, col = src.index(x, y)
        escala = src.res[0]
        mitad = tam // 2 if escala <= 10 else 0  # en bandas de 20 m basta el pixel central
        ventana = Window(col - mitad, fila - mitad, 2 * mitad + 1, 2 * mitad + 1)
        return src.read(1, window=ventana, boundless=True, fill_value=0).astype("float32").ravel()


def espectro(puntos, anio, mes, simultaneos=16):
    """Reflectancia mediana sin nubes por banda en cada punto (DataFrame id × banda)."""
    import mgrs

    conv = mgrs.MGRS()
    puntos = puntos.copy()
    puntos["mosaico"] = [conv.toMGRS(la, lo, MGRSPrecision=0) for la, lo in zip(puntos.lat, puntos.lon)]
    filas = []
    for mosaico, grupo in puntos.groupby("mosaico"):
        items = [i for i in datos.escenas_mosaicos([mosaico], anio, mes, nubes_max=60)
                 if i.id.split("_")[1] == mosaico]
        if not items:
            continue
        epsg = items[0].properties.get("proj:epsg") or int(str(items[0].properties.get("proj:code", "EPSG:0")).split(":")[1])
        tr = Transformer.from_crs(4326, epsg, always_xy=True)
        xy = [tr.transform(lo, la) for la, lo in zip(grupo.lat, grupo.lon)]

        def por_escena(item):
            off = datos._offset(item)
            res = {}
            for (pid, (x, y)) in zip(grupo.id, xy):
                scl = _leer_punto(item.assets["scl"].href, x, y)
                if not np.isin(scl, datos.SCL_VALIDOS).all():
                    continue
                res[pid] = {b: float(np.mean(_leer_punto(item.assets[a].href, x, y)) - off) / 10000
                            for a, b in BANDAS.items()}
            return res

        with ThreadPoolExecutor(simultaneos) as pool:
            for r in pool.map(por_escena, items):
                for pid, vals in r.items():
                    filas.append({"id": pid, **vals})
    if not filas:
        return pd.DataFrame()
    return pd.DataFrame(filas).groupby("id").median()


def indices(e):
    """Índices a partir de reflectancias por banda."""
    n = lambda a, b: (e[a] - e[b]) / (e[a] + e[b])
    return pd.DataFrame({
        "ndvi": n("B08", "B04"),
        "ndre": n("B8A", "B05"),
        "ndmi": n("B08", "B11"),  # humedad de la hoja
        "bsi": ((e.B11 + e.B04) - (e.B08 + e.B02)) / ((e.B11 + e.B04) + (e.B08 + e.B02)),  # suelo desnudo
        "azul_rojo": e.B02 / e.B04,  # tono azulado
        "swir_ratio": e.B12 / e.B11,
        "re_pendiente": (e.B07 - e.B05) / e.B05,  # pendiente del borde rojo
    }, index=e.index)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puntos", type=Path, required=True, help="CSV con id, lat, lon")
    p.add_argument("--meses", nargs="+", required=True, help="AAAA-MM")
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    puntos = pd.read_csv(args.puntos)
    puntos["id"] = puntos["id"].astype(str)
    tablas = []
    for am in args.meses:
        anio, mes = (int(v) for v in am.split("-"))
        e = espectro(puntos, anio, mes)
        if e.empty:
            print(f"{am}: sin datos", flush=True)
            continue
        t = pd.concat([e, indices(e)], axis=1)
        t.columns = [f"{c}_{am}" for c in t.columns]
        tablas.append(t)
        print(f"{am}: {len(e)} puntos con datos", flush=True)
    pd.concat(tablas, axis=1).round(4).to_csv(args.salida)


if __name__ == "__main__":
    main()
