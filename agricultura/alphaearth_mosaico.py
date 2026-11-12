"""Embeddings de AlphaEarth de un año para un mosaico completo, en la rejilla de 20 m de `mosaico.py`.

AlphaEarth (Google DeepMind, CC-BY 4.0) viene a 10 m en archivos de ~82 km por zona UTM
(Source Cooperative en AWS, sin cuenta) y en la misma zona UTM que el mosaico, con las
rejillas alineadas. Por bloques y en paralelo se lee la ventana de 10 m de cada archivo
que toca el bloque y se promedian 2 × 2 pixeles a la rejilla de `uso_suelo.tif` (sin
reproyectar, que con GDAL relee los mismos bloques muchas veces). Se guarda un GeoTIFF de 64 bandas int8 con los valores cuantizados tal cual
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

BLOQUE = 512  # pixeles de 20 m por lado de cada bloque (1024 × 1024 a 10 m)


def archivos_del_mosaico(idx, geobox, anio):
    w, s, e, n = geobox.geographic_extent.boundingbox
    t = idx[(idx.year == anio) & (idx.wgs84_west < e) & (idx.wgs84_east > w)
            & (idx.wgs84_south < n) & (idx.wgs84_north > s)]
    zona = f"{geobox.crs.to_epsg() % 100}N"  # EPSG:326ZZ
    # Primero los del huso propio (rejilla alineada); los del huso vecino solo rellenan huecos
    # (un mosaico MGRS puede salirse de su huso, como 14QRD).
    t = t.assign(otro=t.utm_zone != zona).sort_values("otro")
    return [p.replace("s3://us-west-2.opendata.source.coop", S3) for p in t.path]


def promedio_2x2(a):
    """(64, 2h, 2w) int8 a 10 m -> (64, h, w) int8 a 20 m, promediando sin contar el sin dato."""
    b, h, w = a.shape[0], a.shape[1] // 2, a.shape[2] // 2
    v = a.reshape(b, h, 2, w, 2).astype(np.float32)
    ok = v != SIN_DATO
    n = ok.sum((2, 4))
    s = np.where(ok, v, 0).sum((2, 4))
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.round(s / n)
    return np.where(n > 0, m, SIN_DATO).astype("int8")


def ventana_10m(src, xa, xb, ya, yb):
    """Lee de un archivo de AlphaEarth el rectángulo [xa, xb] × [yb, ya] (UTM) a 10 m, norte arriba."""
    from rasterio.windows import Window
    t = src.transform
    c = (xa - t.c) / t.a
    r = (yb - t.f) / t.e if t.e > 0 else (ya - t.f) / t.e  # los archivos van de sur a norte (e > 0)
    assert abs(c - round(c)) < 1e-6 and abs(r - round(r)) < 1e-6, "rejillas no alineadas"
    ancho, alto = round((xb - xa) / abs(t.a)), round((ya - yb) / abs(t.e))
    a = src.read(window=Window(round(c), round(r), ancho, alto), boundless=True, fill_value=SIN_DATO)
    return a[:, ::-1] if t.e > 0 else a


def otro_huso(src, xa, xb, ya, yb, paso, crs):
    """Ventana de un archivo de otro huso UTM, reproyectada (promedio) al bloque de destino."""
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds
    from rasterio.windows import Window
    t = src.transform
    x0, y0, x1, y1 = transform_bounds(crs, src.crs, xa, yb, xb, ya)
    x0, y0, x1, y1 = x0 - 40, y0 - 40, x1 + 40, y1 + 40
    c0, c1 = int(np.floor((x0 - t.c) / t.a)), int(np.ceil((x1 - t.c) / t.a))
    if t.e > 0:
        r0, r1 = int(np.floor((y0 - t.f) / t.e)), int(np.ceil((y1 - t.f) / t.e))
    else:
        r0, r1 = int(np.floor((y1 - t.f) / t.e)), int(np.ceil((y0 - t.f) / t.e))
    a = src.read(window=Window(c0, r0, c1 - c0, r1 - r0), boundless=True, fill_value=SIN_DATO)
    if t.e > 0:
        a, arriba = a[:, ::-1], t.f + t.e * r1
    else:
        arriba = t.f + t.e * r0
    h, w = round((ya - yb) / paso), round((xb - xa) / paso)
    out = np.full((64, h, w), SIN_DATO, "int8")
    reproject(np.ascontiguousarray(a), out, src_transform=from_origin(t.c + t.a * c0, arriba, t.a, abs(t.e)),
              src_crs=src.crs, src_nodata=SIN_DATO, dst_transform=from_origin(xa, ya, paso, paso),
              dst_crs=crs, dst_nodata=SIN_DATO, resampling=Resampling.average)
    return out


def main(argv=None):
    import rasterio
    from rasterio.warp import transform_bounds

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", required=True)
    p.add_argument("--anio", type=int, default=2025)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "alphaearth")
    p.add_argument("--simultaneos", type=int, default=8)
    args = p.parse_args(argv)

    t0 = time.time()
    geobox = rejilla(args.mosaico)
    alto, ancho = geobox.shape
    X0, Y0, paso = geobox.affine.c, geobox.affine.f, geobox.affine.a
    urls = archivos_del_mosaico(indice(args.cache), geobox, args.anio)
    crs = rasterio.crs.CRS.from_epsg(geobox.crs.to_epsg())
    print(f"{args.mosaico}: {alto} × {ancho} pixeles de {paso:.0f} m; {len(urls)} archivos de "
          f"AlphaEarth {args.anio}", flush=True)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        limites = []
        for u in urls:
            with rasterio.open(u) as src:
                b = src.bounds  # con e > 0 rasterio da "bottom" y "top" al revés
                caja = (b.left, min(b.bottom, b.top), b.right, max(b.bottom, b.top))
                propio = src.crs.to_epsg() == crs.to_epsg()
                limites.append((caja if propio else transform_bounds(src.crs, crs, *caja), propio))

    salida = np.full((64, alto, ancho), SIN_DATO, "int8")
    bloques = [(f, c) for f in range(0, alto, BLOQUE) for c in range(0, ancho, BLOQUE)]
    local = threading.local()
    candado = threading.Lock()
    hechos = [0]

    def abrir(u):
        if not hasattr(local, "abiertos"):
            local.env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4",
                                     GDAL_HTTP_RETRY_DELAY="3")
            local.env.__enter__()
            local.abiertos = {}
        if u not in local.abiertos:
            local.abiertos[u] = rasterio.open(u)
        return local.abiertos[u]

    def uno(b):
        f, c = b
        h, w = min(BLOQUE, alto - f), min(BLOQUE, ancho - c)
        xa, xb = X0 + paso * c, X0 + paso * (c + w)
        ya, yb = Y0 - paso * f, Y0 - paso * (f + h)
        out = salida[:, f:f + h, c:c + w]
        for u, (lim, propio) in zip(urls, limites):
            izq, abajo, der, arriba = lim
            if izq >= xb or der <= xa or abajo >= ya or arriba <= yb:
                continue
            if not (out[0] == SIN_DATO).any():
                break
            for intento in range(4):
                try:
                    a = (promedio_2x2(ventana_10m(abrir(u), xa, xb, ya, yb)) if propio else
                         otro_huso(abrir(u), xa, xb, ya, yb, paso, crs))
                    break
                except Exception:
                    getattr(local, "abiertos", {}).pop(u, None)
                    if intento == 3:
                        raise
                    time.sleep(5 * (intento + 1))
            hueco = out[0] == SIN_DATO
            out[:, hueco] = a[:, hueco]
        with candado:
            hechos[0] += 1
            if hechos[0] % 10 == 0:
                print(f"{hechos[0]}/{len(bloques)} bloques, {(time.time() - t0) / 60:.0f} min", flush=True)

    with ThreadPoolExecutor(args.simultaneos) as ex:
        list(ex.map(uno, bloques))

    destino = args.salida / f"alphaearth_{args.anio}.tif"
    args.salida.mkdir(parents=True, exist_ok=True)
    perfil = dict(driver="GTiff", width=ancho, height=alto, count=64, dtype="int8", nodata=SIN_DATO,
                  crs=geobox.crs.to_wkt(), transform=geobox.affine, tiled=True, blockxsize=512,
                  blockysize=512, compress="zstd", interleave="pixel", BIGTIFF="IF_SAFER")
    with rasterio.open(destino, "w", **perfil) as dst:
        dst.write(salida)
    print(f"Listo en {(time.time() - t0) / 60:.0f} min: {destino} "
          f"({100 * (salida[0] != SIN_DATO).mean():.0f} % con dato)")


if __name__ == "__main__":
    main()
