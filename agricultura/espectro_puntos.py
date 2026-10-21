"""Las 10 bandas de Sentinel-2 en cada punto de verificación, para entrenar con etiquetas reales.

Para cada punto baja solo una ventana de 3 × 3 pixeles (60 m) de los meses que usa
`humedad.py` (abril 2025, abril 2026 y septiembre 2025) y guarda la mediana por banda,
con las mismas columnas que `espectro_muestra.csv.gz` (`B02_2025-04`, ...). Así el
clasificador de `modelo_espectral.py` se puede reentrenar con lo que se marcó a mano sin
bajar mosaicos completos.

Uso:
    python -m agricultura.espectro_puntos \
        --puntos agricultura/resultados/verificacion/puntos_150/puntos_verificacion.csv \
        --salida agricultura/resultados/verificacion/puntos_150/espectro_puntos.csv
"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

from .humedad import MESES, compuesto
from .mosaico import SIN_DATO, rejilla


def ventana(geobox, lat, lon):
    X, Y = pyproj.Transformer.from_crs(4326, geobox.crs.to_wkt(), always_xy=True).transform(lon, lat)
    j = int(np.abs(geobox.coords["x"].values - X).argmin())
    i = int(np.abs(geobox.coords["y"].values - Y).argmin())
    return geobox[i - 1:i + 2, j - 1:j + 2]


def espectro(mosaico, caja):
    fila = {}
    for anio, mes in MESES:
        for intento in range(4):  # la red a veces corta una lectura a medias
            try:
                b = compuesto(mosaico, anio, mes, caja)
                break
            except Exception:
                if intento == 3:
                    raise
                time.sleep(5 * (intento + 1))
        for banda, a in (b or {}).items():
            v = a[a != SIN_DATO]
            fila[f"{banda}_{anio}-{mes:02d}"] = float(np.median(v)) if v.size else np.nan
    return fila


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puntos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--simultaneos", type=int, default=4)
    args = p.parse_args(argv)
    import odc.stac
    odc.stac.configure_rio(cloud_defaults=True)
    puntos = pd.read_csv(args.puntos)
    hecho = pd.read_csv(args.salida) if args.salida.exists() else pd.DataFrame(columns=["id"])
    filas = hecho.to_dict("records")
    listos = set(hecho.id)
    rejillas = {m: rejilla(m) for m in puntos.mosaico.unique()}
    candado = threading.Lock()

    def uno(r):
        if r.id in listos:
            return
        try:
            fila = {"id": r.id, **espectro(r.mosaico, ventana(rejillas[r.mosaico], r.lat, r.lon))}
        except Exception as e:  # se reintenta en la siguiente corrida
            print(f"  {r.id}: falló ({e})", flush=True)
            return
        with candado:
            filas.append(fila)
            pd.DataFrame(filas).to_csv(args.salida, index=False)
            print(f"  {r.id} ({len(filas)}/{len(puntos)})", flush=True)

    with ThreadPoolExecutor(args.simultaneos) as pool:
        list(pool.map(uno, puntos.itertuples()))
    print(f"{len(filas)} puntos con espectro")


if __name__ == "__main__":
    main()
