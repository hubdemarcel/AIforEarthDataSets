"""Puntos para verificar en Google Maps lo que el satélite marca como agave en ciertos municipios.

Toma pixeles clasificados como agave en pie en el interior de zonas homogéneas
(lejos de bordes), separados entre sí, dentro de cada municipio pedido. Sirve para
medir falsos positivos cuando las cifras no cuadran con otras fuentes (p. ej. SIAP).

Uso:
    python -m agricultura.verificacion --municipios Ameca "El Arenal" Tala Cocula \
        --por-municipio 6 --salida agricultura/resultados/verificacion/valles_sur
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
from rasterio.features import rasterize
from scipy import ndimage

from .municipios import MUNICIPIOS, _area_propia

RAIZ = Path(__file__).parent
AGAVE = 4


def puntos(municipios, por_municipio=6, margen=3, distancia_min_m=1500, semilla=0):
    rng = np.random.default_rng(semilla)
    filas = []
    mosaicos = sorted(m for m in (RAIZ / "resultados" / "mosaicos").iterdir() if (m / "uso_suelo.tif").exists())
    for _, mun in municipios.iterrows():
        elegidos = []
        for m in mosaicos:
            uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
            est = rioxarray.open_rasterio(m / "agave_establecimiento.tif").squeeze("band", drop=True).values
            geom = gpd.GeoSeries([mun.geometry], crs=municipios.crs).to_crs(uso.rio.crs).iloc[0]
            dentro = rasterize([(geom, 1)], out_shape=uso.shape, transform=uso.rio.transform(), fill=0,
                               dtype="uint8").astype(bool) & _area_propia(uso)
            if not dentro.any():
                continue
            agave = ndimage.binary_erosion(uso.values == AGAVE, structure=np.ones((2 * margen + 1,) * 2)) & dentro
            fy, fx = np.nonzero(agave)
            for i in rng.permutation(len(fy)):
                x, y = float(uso.x[fx[i]]), float(uso.y[fy[i]])
                if all(np.hypot(x - ex, y - ey) >= distancia_min_m for ex, ey, *_ in elegidos):
                    elegidos.append((x, y, int(est[fy[i], fx[i]]), uso.rio.crs))
                    if len(elegidos) == por_municipio:
                        break
            if len(elegidos) == por_municipio:
                break
        for x, y, anio, crs in elegidos:
            p = gpd.GeoSeries.from_xy([x], [y], crs=crs).to_crs("EPSG:4326").iloc[0]
            filas.append({"municipio": mun.municipio, "anio_establecimiento": anio,
                          "lat": round(p.y, 6), "lon": round(p.x, 6)})
    df = pd.DataFrame(filas)
    df.insert(0, "id", np.arange(1, len(df) + 1))
    df["google_maps"] = [f"https://maps.google.com/?q={a},{o}&t=k" for a, o in zip(df.lat, df.lon)]
    df["es_agave"] = ""
    return df


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--municipios", nargs="+", required=True)
    p.add_argument("--estado", default="Jalisco")
    p.add_argument("--por-municipio", type=int, default=6)
    p.add_argument("--salida", type=Path, required=True, help="ruta sin extensión")
    args = p.parse_args(argv)
    mun = gpd.read_file(MUNICIPIOS)
    mun = mun[(mun.estado == args.estado) & mun.municipio.isin(args.municipios)]
    df = puntos(mun, args.por_municipio)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.salida.with_suffix(".csv"), index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
