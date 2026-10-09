"""Limpieza por predio: delimita predios en la imagen y les asigna clase y edad.

No hay catastro de predios, así que se segmenta la imagen Sentinel-2 de 10 m en
regiones homogéneas usando la imagen actual y el verdor de secas de cada año
desde 2018. Así dos predios vecinos de agave con distinta edad quedan separados.
Cada predio toma la clase mayoritaria de sus pixeles y, si es agave, el año de
establecimiento más frecuente. Se eliminan los pixeles sueltos.

Uso:
    python -m agricultura.predios --resultados agricultura/resultados/tequila
"""

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray
import xarray as xr
from rasterio.enums import Resampling
from rasterio.features import shapes
from shapely.geometry import shape
from skimage.segmentation import felzenszwalb

from . import agave
from .agave import CLASES

AGAVE, COSECHADO = 4, 5


def _capa(ruta, plantilla, metodo=Resampling.nearest):
    capa = rioxarray.open_rasterio(ruta).squeeze("band", drop=True)
    return capa.rio.reproject_match(plantilla, resampling=metodo).values


def _escalar(a):
    """Lleva una capa a ~0–1 con percentiles 2–98 (robusto a valores extremos)."""
    lo, hi = np.nanpercentile(a, [2, 98])
    return np.clip((np.nan_to_num(a, nan=lo) - lo) / (hi - lo + 1e-6), 0, 1)


def segmentar(s2, secas, escala=60, tam_min=30):
    """Etiqueta de predio (y, x) por segmentación Felzenszwalb.

    Usa NDVI de secas y lluvias del último año y SWIR de secas (10 m), más el verdor
    de secas de cada año del histórico (re-muestreado a 10 m). `tam_min` en pixeles
    de 10 m (30 = 0.3 ha).
    """
    ndvi = (s2.B08 - s2.B04) / (s2.B08 + s2.B04)
    capas = [
        ndvi.sel(mes=[3, 4, 5]).median("mes").values,
        ndvi.sel(mes=[8, 9]).median("mes").values,
        s2.B11.sel(mes=[3, 4, 5]).median("mes").values,
    ]
    capas += list(secas)
    pila = np.stack([_escalar(c) for c in capas], axis=-1)
    return felzenszwalb(pila, scale=escala, sigma=0.6, min_size=tam_min, channel_axis=-1) + 1


def por_predio(etiqueta, clase, establecimiento, jima):
    """Clase mayoritaria, fracción y años más frecuentes por predio."""
    df = pd.DataFrame({"predio": etiqueta.ravel(), "clase": clase.ravel(),
                       "est": establecimiento.ravel(), "jima": jima.ravel()})
    df = df[df.clase > 0]
    conteo = df.groupby(["predio", "clase"]).size().unstack(fill_value=0)
    total = conteo.sum(1)
    resumen = pd.DataFrame({"clase": conteo.idxmax(1), "pixeles": total,
                            "fraccion": (conteo.max(1) / total).round(2)})
    resumen["fraccion_agave"] = (conteo.get(AGAVE, 0) / total).round(2)
    # Un predio es agave si al menos la mitad de sus pixeles lo son (aunque otra clase sea mayoría relativa)
    resumen.loc[resumen.fraccion_agave >= 0.5, "clase"] = AGAVE
    moda = lambda s: s[s > 0].mode().min() if (s > 0).any() else 0
    agaves = df[df.clase == AGAVE].groupby("predio").est.agg(moda)
    jimas = df[df.clase == COSECHADO].groupby("predio").jima.agg(moda)
    resumen["establecimiento"] = agaves.reindex(resumen.index).fillna(0).astype(int)
    resumen["jima"] = jimas.reindex(resumen.index).fillna(0).astype(int)
    resumen.loc[resumen.clase != AGAVE, "establecimiento"] = 0
    resumen.loc[resumen.clase != COSECHADO, "jima"] = 0
    return resumen


def poligonos(etiqueta, resumen, plantilla, clases=(AGAVE, COSECHADO)):
    """Polígonos de los predios de las clases indicadas, con atributos."""
    elegidos = resumen.index[resumen.clase.isin(clases)]
    mascara = np.isin(etiqueta, elegidos)
    geoms = [
        (int(v), shape(g))
        for g, v in shapes(etiqueta.astype("int32"), mask=mascara, transform=plantilla.rio.transform())
    ]
    gdf = gpd.GeoDataFrame({"predio": [v for v, _ in geoms]}, geometry=[g for _, g in geoms],
                           crs=plantilla.rio.crs).dissolve("predio").reset_index()
    gdf = gdf.join(resumen, on="predio")
    gdf["hectareas"] = (gdf.area / 10_000).round(2)
    gdf["tipo"] = gdf.clase.map(CLASES)
    centro = gdf.representative_point().to_crs("EPSG:4326")
    gdf["lat"], gdf["lon"] = centro.y.round(6), centro.x.round(6)
    gdf["google_maps"] = [f"https://maps.google.com/?q={a},{o}&t=k" for a, o in zip(gdf.lat, gdf.lon)]
    return gdf


def _grafica(antes, despues, est, anios, ruta):
    colores = ["#ffffff", "#2b6cb0", "#7f7f7f", "#1e5631", "#5fa8a0", "#d4a017", "#e9d8a6", "#8fbc5a", "#c9b79c"]
    cmap = matplotlib.colors.ListedColormap(colores)
    fig, ejes = plt.subplots(1, 3, figsize=(24, 7))
    for ax, datos_, titulo in [(ejes[0], antes, "Por pixel (antes)"), (ejes[1], despues, "Por predio (después)")]:
        ax.imshow(datos_, cmap=cmap, vmin=-0.5, vmax=8.5, interpolation="nearest")
        ax.set_title(titulo)
        ax.axis("off")
    ejes[1].legend(handles=[matplotlib.patches.Patch(color=colores[k], label=v) for k, v in CLASES.items() if k > 0],
                   loc="lower left", fontsize=8, framealpha=0.9)
    im = ejes[2].imshow(np.ma.masked_equal(est, 0), cmap="viridis", vmin=anios.min(), vmax=anios.max(),
                        interpolation="nearest")
    ejes[2].set_title("Predios de agave: año de establecimiento")
    ejes[2].axis("off")
    fig.colorbar(im, ax=ejes[2], fraction=0.035)
    fig.tight_layout()
    fig.savefig(ruta, dpi=120)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resultados", type=Path, required=True,
                   help="carpeta con s2_mensual_*.nc, historico/mensual y agave/")
    p.add_argument("--escala", type=float, default=60, help="mayor = predios más grandes")
    p.add_argument("--tam-min", type=int, default=30, help="tamaño mínimo de predio en pixeles de 10 m")
    args = p.parse_args(argv)
    r = args.resultados
    salida = r / "predios"
    salida.mkdir(exist_ok=True)

    s2 = xr.open_dataset(next(r.glob("s2_mensual_*.nc")), decode_coords="all")[["B04", "B08", "B11"]].load()
    plantilla = s2.B04.isel(mes=0, drop=True)
    plantilla = xr.DataArray(np.zeros(plantilla.shape, "float32"), dims=("y", "x"),
                             coords={"y": plantilla.y, "x": plantilla.x}).rio.write_crs(s2.rio.crs)

    print("Leyendo histórico y mapas por pixel...")
    ndvi = xr.open_mfdataset(sorted((r / "historico" / "mensual").glob("ndvi_*.nc")), combine="by_coords",
                             decode_coords="all").ndvi.load()
    secas, _ = agave.metricas_anuales(ndvi)
    secas = secas.rio.write_crs(ndvi.rio.crs)
    secas_10m = [secas.sel(anio=a).rio.reproject_match(plantilla, resampling=Resampling.bilinear).values
                 for a in secas.anio.values]
    clase = _capa(r / "agave" / "uso_suelo.tif", plantilla)
    est = _capa(r / "agave" / "agave_establecimiento.tif", plantilla)
    jima = _capa(r / "agave" / "agave_jima.tif", plantilla)

    print("Segmentando predios...")
    etiqueta = segmentar(s2, secas_10m, args.escala, args.tam_min)
    resumen = por_predio(etiqueta, clase, est, jima)
    print(f"  {len(resumen):,} predios / regiones")

    clase_p = resumen.clase.reindex(np.arange(etiqueta.max() + 1), fill_value=0).values[etiqueta]
    est_p = resumen.establecimiento.reindex(np.arange(etiqueta.max() + 1), fill_value=0).values[etiqueta]
    exportar = lambda v, n: plantilla.copy(data=v.astype("uint16")).rio.write_nodata(0).rio.to_raster(salida / n)
    exportar(clase_p, "uso_suelo_predios.tif")
    exportar(est_p, "agave_establecimiento_predios.tif")

    gdf = poligonos(etiqueta, resumen, plantilla)
    gdf["edad_2026"] = np.where(gdf.establecimiento > 0, 2026 - gdf.establecimiento, 0)
    columnas = ["predio", "tipo", "hectareas", "establecimiento", "edad_2026", "jima", "fraccion",
                "lat", "lon", "google_maps", "geometry"]
    gdf = gdf[columnas].sort_values(["tipo", "establecimiento", "hectareas"], ascending=[True, True, False])
    gdf.to_crs("EPSG:4326").to_file(salida / "predios_agave.geojson", driver="GeoJSON")
    gdf.drop(columns="geometry").to_csv(salida / "predios_agave.csv", index=False)

    ha_px = 0.01
    sup = pd.Series(clase_p.ravel()).value_counts().sort_index()
    tabla = pd.DataFrame({"clase": [CLASES[k] for k in sup.index], "hectareas": (sup.values * ha_px).round(0)})
    tabla[tabla.clase != "sin dato"].to_csv(salida / "superficie_predios.csv", index=False)
    agaves = gdf[gdf.tipo == CLASES[AGAVE]]
    por_anio = agaves.groupby("establecimiento").agg(predios=("predio", "size"), hectareas=("hectareas", "sum"),
                                                    ha_mediana_predio=("hectareas", "median")).round(1)
    por_anio.to_csv(salida / "agave_por_anio_predios.csv")
    cosechados = gdf[gdf.tipo == CLASES[COSECHADO]].groupby("jima").agg(
        predios=("predio", "size"), hectareas=("hectareas", "sum")).round(1)
    cosechados.to_csv(salida / "agave_jima_predios.csv")

    antes = _capa(r / "agave" / "uso_suelo.tif", plantilla)
    _grafica(antes, clase_p, est_p, secas.anio.values, salida / "predios.png")
    print(tabla[tabla.clase != "sin dato"].to_string(index=False))
    print("\nAgave en pie por año de establecimiento:")
    print(por_anio.to_string())
    print("\nAgave cosechado sin replantar:")
    print(cosechados.to_string())


if __name__ == "__main__":
    main()
