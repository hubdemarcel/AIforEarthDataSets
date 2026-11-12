"""Embeddings de AlphaEarth de un año para un mosaico completo, en la rejilla de 20 m de `mosaico.py`.

AlphaEarth (Google DeepMind, CC-BY 4.0) viene a 10 m en archivos de ~82 km por zona UTM
(Source Cooperative en AWS, sin cuenta). Aquí se reproyecta cada archivo que toca el
mosaico a la rejilla de `uso_suelo.tif` promediando 2 × 2 pixeles, por bloques y en
paralelo, y se guarda un GeoTIFF de 64 bandas int8 con los valores cuantizados tal cual
(desde-cuantizar con `embeddings_puntos.descuantizar`).

Uso:
    python -m agricultura.alphaearth_mosaico --mosaico 14QQD --anio 2025 \
        --salida agricultura/resultados/mezcal/14QQD
"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .embeddings_puntos import S3, SIN_DATO, indice
from .mosaico import rejilla

BLOQUE = 512  # pixeles de 20 m por lado de cada bloque (≈ 4 bloques internos de AlphaEarth)


def archivos_del_mosaico(idx, geobox, anio):
    w, s, e, n = geobox.geographic_extent.boundingbox
    t = idx[(idx.year == anio) & (idx.wgs84_west < e) & (idx.wgs84_east > w)
            & (idx.wgs84_south < n) & (idx.wgs84_north > s)]
    zona = geobox.crs.to_epsg() % 100  # EPSG:326ZZ
    t = t[t.utm_zone == f"{zona}N"]
    return [p.replace("s3://us-west-2.opendata.source.coop", S3) for p in t.path]


def main(argv=None):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import Window

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", required=True)
    p.add_argument("--anio", type=int, default=2025)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "alphaearth")
    p.add_argument("--simultaneos", type=int, default=12)
    args = p.parse_args(argv)

    t0 = time.time()
    geobox = rejilla(args.mosaico)
    alto, ancho = geobox.shape
    urls = archivos_del_mosaico(indice(args.cache), geobox, args.anio)
    print(f"{args.mosaico}: {alto} × {ancho} pixeles de 20 m; {len(urls)} archivos de AlphaEarth {args.anio}",
          flush=True)

    destino = args.salida / f"alphaearth_{args.anio}.tif"
    args.salida.mkdir(parents=True, exist_ok=True)
    perfil = dict(driver="GTiff", width=ancho, height=alto, count=64, dtype="int8", nodata=SIN_DATO,
                  crs=geobox.crs.to_wkt(), transform=geobox.affine, tiled=True, blockxsize=BLOCK_SALIDA,
                  blockysize=BLOCK_SALIDA, compress="zstd", interleave="pixel", BIGTIFF="IF_SAFER")
    bloques = [(f, c) for f in range(0, alto, BLOQUE) for c in range(0, ancho, BLOQUE)]
    local = threading.local()
    candado = threading.Lock()
    hechos = [0]

    def vrts():
        if not hasattr(local, "vrts"):
            local.env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                                     GDAL_HTTP_RETRY_DELAY="3", GDAL_CACHEMAX=256)
            local.env.__enter__()
            local.vrts = []
            for u in urls:
                src = rasterio.open(u)
                local.vrts.append(WarpedVRT(src, crs=perfil["crs"], transform=geobox.affine, width=ancho,
                                            height=alto, resampling=Resampling.average,
                                            src_nodata=SIN_DATO, nodata=SIN_DATO))
        return local.vrts

    with rasterio.open(destino, "w", **perfil) as dst:
        def uno(b):
            f, c = b
            ventana = Window(c, f, min(BLOQUE, ancho - c), min(BLOQUE, alto - f))
            salida = np.full((64, int(ventana.height), int(ventana.width)), SIN_DATO, "int8")
            for intento in range(4):
                try:
                    for v in vrts():
                        a = v.read(window=ventana)
                        hueco = salida[0] == SIN_DATO
                        salida[:, hueco] = a[:, hueco]
                    break
                except Exception:
                    if hasattr(local, "vrts"):
                        del local.vrts
                    if intento == 3:
                        raise
                    time.sleep(5 * (intento + 1))
            with candado:
                dst.write(salida, window=ventana)
                hechos[0] += 1
                if hechos[0] % 20 == 0:
                    print(f"{hechos[0]}/{len(bloques)} bloques, {(time.time() - t0) / 60:.0f} min", flush=True)

        with ThreadPoolExecutor(args.simultaneos) as ex:
            list(ex.map(uno, bloques))
    print(f"Listo en {(time.time() - t0) / 60:.0f} min: {destino}")


BLOCK_SALIDA = 512

if __name__ == "__main__":
    main()
