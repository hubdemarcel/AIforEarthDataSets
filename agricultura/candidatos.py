"""Puntos candidatos por grupo para verificar en campo o en Google Maps.

Elige pixeles en el interior de zonas homogéneas de cada grupo (lejos de bordes) y
separados entre sí, y los exporta con coordenadas y liga a Google Maps. Después de
verificar, se escribe la clase real en la columna `clase` y el archivo se usa como
etiquetas en `pipeline.py --etiquetas`.

Uso:
    python -m agricultura.candidatos --grupos agricultura/resultados/tequila/grupos.tif \
        --por-grupo 4 --salida agricultura/resultados/tequila/candidatos
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import rioxarray
from scipy import ndimage


def elegir(grupo, por_grupo=4, margen_pixeles=4, distancia_min_m=1500, semilla=0):
    """Puntos (GeoDataFrame en lat/lon) en el interior de cada grupo."""
    valores = grupo.values
    x, y = grupo.x.values, grupo.y.values
    rng = np.random.default_rng(semilla)
    estructura = np.ones((2 * margen_pixeles + 1,) * 2, dtype=bool)
    filas = []
    for g in np.unique(valores[valores > 0]):
        interior = ndimage.binary_erosion(valores == g, structure=estructura)
        fy, fx = np.nonzero(interior)
        elegidos = []
        for i in rng.permutation(len(fy)):
            px, py = x[fx[i]], y[fy[i]]
            if all(np.hypot(px - ex, py - ey) >= distancia_min_m for ex, ey in elegidos):
                elegidos.append((px, py))
                if len(elegidos) == por_grupo:
                    break
        filas += [{"grupo": int(g), "x": px, "y": py} for px, py in elegidos]

    puntos = gpd.GeoDataFrame(
        filas, geometry=gpd.points_from_xy([f["x"] for f in filas], [f["y"] for f in filas]), crs=grupo.rio.crs
    ).to_crs("EPSG:4326")
    puntos["lat"] = puntos.geometry.y.round(6)
    puntos["lon"] = puntos.geometry.x.round(6)
    puntos["google_maps"] = [
        f"https://maps.google.com/?q={la},{lo}&t=k" for la, lo in zip(puntos.lat, puntos.lon)
    ]
    puntos["clase"] = ""
    puntos.insert(0, "id", np.arange(1, len(puntos) + 1))
    return puntos.drop(columns=["x", "y"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--grupos", type=Path, required=True, help="grupos.tif de pipeline.py")
    p.add_argument("--por-grupo", type=int, default=4)
    p.add_argument("--salida", type=Path, required=True, help="ruta sin extensión")
    args = p.parse_args(argv)

    grupo = rioxarray.open_rasterio(args.grupos).squeeze("band", drop=True)
    puntos = elegir(grupo, args.por_grupo)
    puntos.to_file(args.salida.with_suffix(".geojson"), driver="GeoJSON")
    puntos.drop(columns="geometry").to_csv(args.salida.with_suffix(".csv"), index=False)
    print(puntos.drop(columns="geometry").to_string(index=False))


if __name__ == "__main__":
    main()
