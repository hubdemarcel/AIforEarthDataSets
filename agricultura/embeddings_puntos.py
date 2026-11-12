"""Embeddings de AlphaEarth (Google DeepMind) en cada punto de verificación, 2018–2025.

AlphaEarth resume en 64 números por pixel de 10 m y por año todo lo que vieron
Sentinel-2, Sentinel-1 (radar), Landsat y el relieve. Es gratis (CC-BY 4.0, "produced by
Google and Google DeepMind") y está en AWS sin cuenta (Source Cooperative, `tge-labs/aef`).

Por punto y año baja solo una ventana de 3 × 3 pixeles (30 m) y guarda la mediana de
cada dimensión, ya desde-cuantizada ((v / 127.5)² · signo(v)). Así se puede probar si
los embeddings separan el agave de sus imitadores sin bajar mosaicos.

El índice de archivos (`aef_index.parquet`, 78 MB) se baja una vez a `--cache`.

Uso:
    python -m agricultura.embeddings_puntos \
        --puntos agricultura/resultados/verificacion/mezcal_200/puntos_mezcal.csv \
        --salida agricultura/resultados/verificacion/mezcal_200/alphaearth.csv.gz
"""

import argparse
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj

S3 = "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop"
INDICE = f"{S3}/tge-labs/aef/v1/annual/aef_index.parquet"
ANIOS = list(range(2018, 2026))
DIMS = [f"A{k:02d}" for k in range(64)]
SIN_DATO = -128

_local = threading.local()


def indice(cache: Path) -> pd.DataFrame:
    ruta = cache / "aef_index.parquet"
    if not ruta.exists():
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(INDICE, ruta)
    cols = ["path", "year", "utm_zone", "wgs84_west", "wgs84_south", "wgs84_east", "wgs84_north"]
    return pd.read_parquet(ruta, columns=cols)


def descuantizar(v):
    """int8 de AlphaEarth -> valor del embedding: (v / 127.5)² · signo(v); el sin dato queda en NaN."""
    v = np.asarray(v, np.float32)
    v = np.where(v == SIN_DATO, np.nan, v)
    return np.sign(v) * (v / 127.5) ** 2


def zona_utm(lat, lon):
    return f"{int((lon + 180) // 6) + 1}{'N' if lat >= 0 else 'S'}"


def archivo(idx, lat, lon, anio):
    """Ruta https del GeoTIFF que cubre el punto en su propia zona UTM (o None)."""
    s = idx[(idx.year == anio) & (idx.wgs84_west <= lon) & (idx.wgs84_east >= lon)
            & (idx.wgs84_south <= lat) & (idx.wgs84_north >= lat)]
    propia = s[s.utm_zone == zona_utm(lat, lon)]
    s = propia if len(propia) else s
    return None if s.empty else s.path.iloc[0].replace("s3://us-west-2.opendata.source.coop", S3)


def _abrir(url):
    import rasterio
    abiertos = getattr(_local, "abiertos", None)
    if abiertos is None:
        _local.env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                                  GDAL_HTTP_RETRY_DELAY="3")
        _local.env.__enter__()
        abiertos = _local.abiertos = {}
    if url not in abiertos:
        abiertos[url] = rasterio.open(url)
    return abiertos[url]


def leer(url, lat, lon):
    for intento in range(4):  # la red a veces corta una lectura a medias
        try:
            ds = _abrir(url)
            X, Y = pyproj.Transformer.from_crs(4326, ds.crs, always_xy=True).transform(lon, lat)
            i, j = ds.index(X, Y)  # el índice respeta la orientación (los archivos van de sur a norte)
            v = ds.read(window=((i - 1, i + 2), (j - 1, j + 2))).reshape(64, -1).astype(np.float32)
            break
        except Exception:
            getattr(_local, "abiertos", {}).pop(url, None)
            if intento == 3:
                raise
            time.sleep(5 * (intento + 1))
    v = descuantizar(v)
    if np.isnan(v).all():
        return None
    return np.nanmedian(v, axis=1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puntos", type=Path, required=True, help="CSV con columnas id, lat, lon")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "alphaearth")
    p.add_argument("--anios", type=int, nargs="+", default=ANIOS)
    p.add_argument("--simultaneos", type=int, default=12)
    args = p.parse_args(argv)

    idx = indice(args.cache)
    puntos = pd.read_csv(args.puntos)
    # Cada lectura baja las 64 bandas en bloques de 1024 × 1024 (decenas de MB): es lento,
    # así que se guarda cada lectura en un archivo parcial y se reanuda desde ahí.
    parcial = args.salida.with_name(args.salida.name + ".parcial.csv")
    hechas = set()
    if parcial.exists():
        hechas = set(map(tuple, pd.read_csv(parcial, usecols=["id", "anio"]).astype(str).values))
    tareas = [(r.id, r.lat, r.lon, a) for r in puntos.itertuples() for a in args.anios
              if (str(r.id), str(a)) not in hechas]
    print(f"{len(tareas)} lecturas pendientes ({len(hechas)} ya hechas)", flush=True)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    hechos = [0]
    candado = threading.Lock()

    def una(t):
        pid, lat, lon, anio = t
        url = archivo(idx, lat, lon, anio)
        v = leer(url, lat, lon) if url else None
        fila = {"id": pid, "anio": anio, **dict(zip(DIMS, np.round(v, 5) if v is not None else [np.nan] * 64))}
        with candado:
            pd.DataFrame([fila]).to_csv(parcial, mode="a", header=not parcial.exists(), index=False)
            hechos[0] += 1
            if hechos[0] % 100 == 0:
                print(f"{hechos[0]}/{len(tareas)}", flush=True)

    with ThreadPoolExecutor(args.simultaneos) as ex:
        list(ex.map(una, tareas))
    filas = pd.read_csv(parcial).dropna(subset=DIMS, how="all").drop_duplicates(["id", "anio"])
    filas.sort_values(["id", "anio"]).to_csv(args.salida, index=False)
    parcial.unlink()
    print(f"{len(filas)} filas (punto × año) en {args.salida}")


if __name__ == "__main__":
    main()
