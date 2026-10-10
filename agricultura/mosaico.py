"""Procesa un mosaico completo de Sentinel-2 (~110 x 110 km) en su rejilla nativa.

Para escalar a toda la denominación de origen se trabaja un mosaico MGRS a la vez:
cada imagen se lee una sola vez y cada mosaico es una tarea independiente que se
puede reanudar. Solo se bajan los meses que usan las reglas de agave (secas
mar–may y lluvias jul–oct), a 20 m, y cada mes se guarda como NDVI entero
comprimido. Después se calculan las métricas anuales y la clasificación de agave
por bloques de filas para no agotar la memoria.

Uso:
    python -m agricultura.mosaico --mosaico 13QFD --desde 2018 --hasta 2026 \
        --salida agricultura/resultados/mosaicos/13QFD
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401  (activa el accesor .rio)
import xarray as xr

from . import agave, datos

MESES = sorted(agave.SECAS + agave.LLUVIAS)
ESCALA = 10000  # NDVI guardado como entero: valor * 10000
SIN_DATO = -32768
RESOLUCION = 20


def rejilla(mosaico, resolucion=RESOLUCION):
    """GeoBox nativo del mosaico (109.8 km de lado), leído de la banda roja de una escena."""
    import rasterio
    from odc.geo.geobox import GeoBox

    for anio in (2024, 2023, 2022):
        items = datos.escenas_mosaicos([mosaico], anio, 4, nubes_max=100)
        if items:
            break
    with rasterio.open(items[0].assets["red"].href) as src:
        return GeoBox.from_bbox(tuple(src.bounds), crs=src.crs.to_wkt(), resolution=resolucion)


def ndvi_mes(mosaico, anio, mes, geobox):
    """NDVI mediano sin nubes del mes en el mosaico (int16 x10000), o None."""
    import odc.stac

    items = datos.escenas_mosaicos([mosaico], anio, mes)
    if not items:
        return None, 0
    ds = odc.stac.load(items, bands=["red", "nir", "scl"], geobox=geobox, groupby="solar_day",
                       chunks={"x": 1830, "y": 1830}, resampling={"scl": "nearest", "*": "average"})
    offset_dia = {np.datetime64(i.datetime.replace(tzinfo=None), "D"): datos._offset(i) for i in items}
    offset = xr.DataArray([offset_dia.get(np.datetime64(t, "D"), 0) for t in ds.time.values], dims="time")
    valido = ds.scl.isin(datos.SCL_VALIDOS) & (ds.red > 0) & (ds.nir > 0)
    rojo = ds.red.astype("float32") - offset
    nir = ds.nir.astype("float32") - offset
    ndvi = ((nir - rojo) / (nir + rojo)).where(valido).median("time").compute()
    entero = np.where(np.isfinite(ndvi.values), np.round(ndvi.values * ESCALA), SIN_DATO).astype("int16")
    return entero, len(ds.time)


def descargar(mosaico, anios, carpeta, simultaneos=3):
    """NDVI mensual de los meses de secas y lluvias; un archivo .npz por mes (reanudable)."""
    import odc.stac

    odc.stac.configure_rio(cloud_defaults=True)
    carpeta.mkdir(parents=True, exist_ok=True)
    geobox = rejilla(mosaico)

    def bajar(periodo):
        anio, mes = periodo
        ruta = carpeta / f"ndvi_{anio}-{mes:02d}.npz"
        if ruta.exists():
            return
        inicio = time.time()
        ndvi, fechas = ndvi_mes(mosaico, anio, mes, geobox)
        if ndvi is None:
            print(f"  {anio}-{mes:02d}: sin escenas útiles", flush=True)
            return
        np.savez_compressed(ruta, ndvi=ndvi)
        print(f"  {anio}-{mes:02d}: {fechas} fechas en {time.time() - inicio:.0f} s", flush=True)

    periodos = [(a, m) for a in anios for m in MESES]
    with ThreadPoolExecutor(simultaneos) as pool:
        list(pool.map(bajar, periodos))
    return geobox


def metricas(carpeta, anios, alto, ancho, filas_bloque=500):
    """Verdor de secas y amplitud por año (años, alto, ancho) float32, por bloques de filas."""
    archivos = {(int(p.stem[5:9]), int(p.stem[10:12])): p for p in carpeta.glob("ndvi_*.npz")}
    secas = np.full((len(anios), alto, ancho), np.nan, dtype="float32")
    lluvias = np.full_like(secas, np.nan)
    for i, anio in enumerate(anios):
        def leer(meses):
            capas = [np.load(archivos[(anio, m)])["ndvi"] for m in meses if (anio, m) in archivos]
            if not capas:
                return None
            pila = np.stack(capas).astype("float32")
            pila[pila == SIN_DATO] = np.nan
            return pila / ESCALA

        s, ll = leer(agave.SECAS), leer(agave.LLUVIAS)
        with np.errstate(all="ignore"):
            for f in range(0, alto, filas_bloque):
                b = slice(f, f + filas_bloque)
                if s is not None:
                    secas[i, b] = np.nanmedian(s[:, b], 0)
                if ll is not None:
                    lluvias[i, b] = agave._cuantil(ll[:, b], 0.9)
    return secas, lluvias - secas


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", required=True, help="mosaico MGRS, p. ej. 13QFD")
    p.add_argument("--desde", type=int, default=2018)
    p.add_argument("--hasta", type=int, default=2026)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--simultaneos", type=int, default=3)
    args = p.parse_args(argv)
    anios = list(range(args.desde, args.hasta + 1))
    args.salida.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"Descargando NDVI de {args.mosaico} ({len(anios)} años x {len(MESES)} meses)...", flush=True)
    geobox = descargar(args.mosaico, anios, args.salida / "mensual", args.simultaneos)
    t_descarga = time.time() - t0
    alto, ancho = geobox.shape

    print("Calculando métricas anuales...", flush=True)
    secas, amp = metricas(args.salida / "mensual", anios, alto, ancho)
    coords = {"anio": anios, "y": geobox.coords["y"].values, "x": geobox.coords["x"].values}
    plantilla = xr.DataArray(np.zeros((alto, ancho), "float32"), dims=("y", "x"),
                             coords={"y": coords["y"], "x": coords["x"]}).rio.write_crs(geobox.crs.to_wkt())

    print("Pendiente y clasificación...", flush=True)
    bbox = tuple(geobox.geographic_extent.boundingbox)
    pendiente = datos.elevacion(bbox, plantilla).pendiente.values
    clase = np.zeros((alto, ancho), "uint8")
    est = np.zeros((alto, ancho), "uint16")
    jima = np.zeros((alto, ancho), "uint16")
    with np.errstate(all="ignore"):
        mediana = np.nanmedian(secas, 0)
    for f in range(0, alto, 500):
        b = slice(f, f + 500)
        n = secas[:, b].shape[1] * ancho
        r = agave.clasificar(secas[:, b].reshape(len(anios), n), amp[:, b].reshape(len(anios), n),
                             pendiente[b].reshape(n), mediana[b].reshape(n))
        a = lambda idx: np.where(idx >= 0, np.array(anios)[np.clip(idx, 0, None)], 0)
        clase[b] = r["clase"].reshape(-1, ancho)
        est[b] = a(r["establecimiento"]).reshape(-1, ancho)
        jima[b] = a(r["jima"]).reshape(-1, ancho)

    def exportar(valores, nombre):
        plantilla.copy(data=valores).rio.write_nodata(0).rio.to_raster(args.salida / nombre, compress="deflate")

    exportar(clase, "uso_suelo.tif")
    exportar(est, "agave_establecimiento.tif")
    exportar(jima, "agave_jima.tif")
    # Métricas anuales (NDVI x10000 en enteros) para reusarlas sin volver a bajar imágenes
    a_entero = lambda arr: np.where(np.isfinite(arr), np.round(arr * ESCALA), SIN_DATO).astype("int16")
    np.savez_compressed(args.salida / "metricas_anuales.npz", anios=np.array(anios), secas=a_entero(secas),
                        amplitud=a_entero(amp), x=coords["x"], y=coords["y"], crs=geobox.crs.to_wkt())

    ha = RESOLUCION**2 / 10_000
    sup = pd.Series(clase.ravel()).value_counts().sort_index()
    tabla = pd.DataFrame({"clase": [agave.CLASES[k] for k in sup.index], "hectareas": (sup.values * ha).round(0)})
    tabla = tabla[tabla.clase != "sin dato"]
    tabla.to_csv(args.salida / "superficie_uso_suelo.csv", index=False)
    por_anio = (pd.Series(est[clase == 4]).value_counts().sort_index() * ha).round(0)
    por_anio.rename_axis("anio_establecimiento").rename("hectareas").to_csv(
        args.salida / "agave_por_anio_establecimiento.csv")
    t_total = time.time() - t0
    (args.salida / "tiempos.txt").write_text(
        f"descarga_s={t_descarga:.0f}\ntotal_s={t_total:.0f}\npixeles={alto * ancho}\n")
    print(tabla.to_string(index=False))
    print("\nAgave en pie por año de establecimiento (ha):")
    print(por_anio.to_string())
    print(f"\nTiempo: descarga {t_descarga / 60:.0f} min, total {t_total / 60:.0f} min")


if __name__ == "__main__":
    main()
