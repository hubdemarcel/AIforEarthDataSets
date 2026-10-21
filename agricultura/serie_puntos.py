"""Historia de verdor de cada punto de verificación, para mostrarla al que marca.

Por punto y año da el verdor de secas (NDVI mediano de marzo a mayo) y la amplitud
(lluvias − secas), con la mediana de 3 × 3 pixeles (60 m). Lee las métricas ya guardadas
del mosaico (`metricas_historia.npz`, 2009–2026, o `metricas_anuales.npz`, 2018–2026);
si el mosaico no las tiene, baja de Sentinel-2 solo la ventana del punto (2018–2026).

Uso:
    python -m agricultura.serie_puntos \
        --puntos agricultura/resultados/verificacion/puntos_150/puntos_verificacion.csv \
        --salida agricultura/resultados/verificacion/puntos_150/serie_puntos.json
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

from . import agave
from .mosaico import ESCALA, MESES, SIN_DATO, ndvi_mes, rejilla

MOSAICOS = Path(__file__).parent / "resultados" / "mosaicos"
ANIOS_S2 = list(range(2018, 2027))


def _ventana(x, y, X, Y):
    j, i = int(np.abs(x - X).argmin()), int(np.abs(y - Y).argmin())
    return slice(i - 1, i + 2), slice(j - 1, j + 2)


def de_metricas(ruta, lat, lon):
    z = ruta if isinstance(ruta, dict) else np.load(ruta, allow_pickle=True)
    X, Y = pyproj.Transformer.from_crs(4326, str(z["crs"]), always_xy=True).transform(lon, lat)
    fi, co = _ventana(z["x"], z["y"], X, Y)
    med = lambda a: [None if np.isnan(v) else round(float(v) / ESCALA, 2) for v in
                     np.nanmedian(np.where(a[:, fi, co] == SIN_DATO, np.nan, a[:, fi, co]).reshape(len(a), -1), 1)]
    with np.errstate(all="ignore"):
        return {"anios": z["anios"].tolist(), "secas": med(z["secas"]), "amplitud": med(z["amplitud"])}


def de_sentinel(mosaico, geobox, lat, lon):
    X, Y = pyproj.Transformer.from_crs(4326, geobox.crs.to_wkt(), always_xy=True).transform(lon, lat)
    fi, co = _ventana(geobox.coords["x"].values, geobox.coords["y"].values, X, Y)
    caja = geobox[fi, co]
    secas, amp = [], []
    for anio in ANIOS_S2:
        mes = {}
        for m in MESES:
            for intento in range(4):  # la red a veces corta una lectura a medias
                try:
                    nd, _ = ndvi_mes(mosaico, anio, m, caja)
                    break
                except Exception:
                    if intento == 3:
                        raise
                    time.sleep(5 * (intento + 1))
            if nd is not None:
                v = nd.astype("float32"); v[nd == SIN_DATO] = np.nan
                mes[m] = np.nanmedian(v / ESCALA) if np.isfinite(v).any() else np.nan
        with np.errstate(all="ignore"):
            s = np.nanmedian([mes.get(m, np.nan) for m in agave.SECAS])
            ll = [mes[m] for m in agave.LLUVIAS if np.isfinite(mes.get(m, np.nan))]
            a = np.quantile(ll, 0.9) - s if ll else np.nan
        secas.append(None if np.isnan(s) else round(float(s), 2))
        amp.append(None if np.isnan(a) else round(float(a), 2))
    return {"anios": ANIOS_S2, "secas": secas, "amplitud": amp}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puntos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    import odc.stac
    odc.stac.configure_rio(cloud_defaults=True)
    puntos = pd.read_csv(args.puntos)
    candado = threading.Lock()
    hecho = json.loads(args.salida.read_text()) if args.salida.exists() else {}

    def uno(r):
        if r.id in hecho:
            return
        carpeta = MOSAICOS / r.mosaico
        for nombre in ("metricas_historia.npz", "metricas_anuales.npz"):
            if (carpeta / nombre).exists():
                hecho[r.id] = de_metricas(carpeta / nombre, r.lat, r.lon)
                return
        serie = de_sentinel(r.mosaico, rejillas[r.mosaico], r.lat, r.lon)
        with candado:
            hecho[r.id] = serie
            args.salida.write_text(json.dumps(hecho))
        print(f"  {r.id} {r.mosaico}: {hecho[r.id]['secas']}", flush=True)

    sin = sorted({m for m in puntos.mosaico if not any((MOSAICOS / m / n).exists()
                  for n in ("metricas_historia.npz", "metricas_anuales.npz"))})
    rejillas = {m: rejilla(m) for m in sin}
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(uno, (r for r in puntos.itertuples())))
    args.salida.write_text(json.dumps(hecho))
    print(f"{len(hecho)} puntos con historia")


if __name__ == "__main__":
    main()
