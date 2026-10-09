"""Lectura de predios etiquetados y extracción de pixeles de entrenamiento."""

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize

from .config import CLASES


def leer(ruta, campo="clase"):
    """Lee un GeoJSON/GPKG/SHP de polígonos o puntos con el nombre de la clase en `campo`."""
    gdf = gpd.read_file(ruta)
    if campo not in gdf.columns:
        raise ValueError(f"Las etiquetas no tienen el campo '{campo}'. Campos: {list(gdf.columns)}")
    gdf = gdf[gdf[campo].notna() & gdf.geometry.notna()].copy()
    gdf["clase"] = gdf[campo].astype(str).str.strip().str.lower()
    desconocidas = sorted(set(gdf.clase) - set(CLASES))
    if desconocidas:
        raise ValueError(f"Clases desconocidas {desconocidas}. Válidas: {sorted(CLASES)}")
    gdf["codigo"] = gdf.clase.map(CLASES)
    gdf["id_predio"] = np.arange(1, len(gdf) + 1)
    return gdf


def muestrear(pila, gdf, max_por_predio=200, semilla=0):
    """Pixeles de entrenamiento dentro de cada predio.

    Devuelve X (n, caracteristicas), y (códigos de clase) y grupos (id de predio).
    Se limita el número de pixeles por predio para que los predios grandes no
    dominen el modelo, y los grupos permiten validar con predios no vistos.
    """
    gdf = gdf.to_crs(pila.rio.crs)
    _, alto, ancho = pila.shape
    ids = rasterize(
        zip(gdf.geometry, gdf.id_predio),
        out_shape=(alto, ancho),
        transform=pila.rio.transform(),
        fill=0,
        dtype="int32",
    )
    codigo_de = dict(zip(gdf.id_predio, gdf.codigo))
    rng = np.random.default_rng(semilla)
    filas, columnas, grupos = [], [], []
    for id_predio in np.unique(ids[ids > 0]):
        f, c = np.nonzero(ids == id_predio)
        if len(f) > max_por_predio:
            elegidos = rng.choice(len(f), max_por_predio, replace=False)
            f, c = f[elegidos], c[elegidos]
        filas.append(f)
        columnas.append(c)
        grupos.append(np.full(len(f), id_predio))
    if not filas:
        raise ValueError("Ninguna etiqueta cae dentro de la zona descargada")

    filas, columnas, grupos = map(np.concatenate, (filas, columnas, grupos))
    X = pila.values[:, filas, columnas].T
    y = np.array([codigo_de[g] for g in grupos])
    sin_pixel = len(gdf) - len(np.unique(grupos))
    if sin_pixel:
        print(f"  Aviso: {sin_pixel} etiquetas quedaron fuera de la zona o son menores a un pixel")
    return X, y, grupos
