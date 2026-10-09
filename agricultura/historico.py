"""Historia de verdor de varios años (Sentinel-2 desde 2018).

El maíz repite su ciclo cada año; el agave ocupa el predio 5–7 años: suelo casi
desnudo al plantar, verdor que sube poco a poco y se mantiene en secas, y una
caída brusca en la jima. Este módulo descarga el NDVI mensual de varios años y
grafica la historia de puntos (p. ej. los candidatos a verificar).

Uso:
    python -m agricultura.historico --zona tequila --desde 2018-01 \
        --puntos agricultura/resultados/tequila/candidatos.csv \
        --salida agricultura/resultados/tequila/historico
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from . import datos
from .config import ZONAS


def _meses(desde, hasta):
    anio, mes = desde
    while (anio, mes) <= hasta:
        yield anio, mes
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def ndvi_mes(bbox, anio, mes, resolucion=20, nubes_max=70):
    """NDVI mediano sin nubes del mes (y, x), o None si no hay escenas."""
    import odc.stac

    items = datos.escenas_s2(bbox, anio, mes, nubes_max)
    if not items:
        return None
    ds = odc.stac.load(
        items,
        bands=["red", "nir", "scl"],
        bbox=bbox,
        crs=f"EPSG:{datos.epsg_utm(bbox)}",
        resolution=resolucion,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
    )
    offset_dia = {np.datetime64(i.datetime.replace(tzinfo=None), "D"): datos._offset(i) for i in items}
    offset = xr.DataArray([offset_dia.get(np.datetime64(t, "D"), 0) for t in ds.time.values], dims="time")
    valido = ds.scl.isin(datos.SCL_VALIDOS) & (ds.red > 0) & (ds.nir > 0)
    rojo = ds.red.astype("float32") - offset
    nir = ds.nir.astype("float32") - offset
    ndvi = ((nir - rojo) / (nir + rojo)).where(valido)
    return ndvi.median("time").astype("float32").compute()


def descargar(bbox, desde, hasta, carpeta, resolucion=20, simultaneos=6):
    """NDVI mensual (tiempo, y, x). Cada mes se guarda aparte para poder reanudar."""
    import odc.stac

    odc.stac.configure_rio(cloud_defaults=True)
    carpeta.mkdir(parents=True, exist_ok=True)

    def bajar(periodo):
        anio, mes = periodo
        ruta = carpeta / f"ndvi_{anio}-{mes:02d}.nc"
        if ruta.exists():
            return ruta
        ndvi = ndvi_mes(bbox, anio, mes, resolucion)
        if ndvi is None:
            print(f"  {anio}-{mes:02d}: sin escenas útiles", flush=True)
            return None
        ndvi.expand_dims(tiempo=[np.datetime64(f"{anio}-{mes:02d}-15")]).rename("ndvi").to_netcdf(ruta)
        print(f"  {anio}-{mes:02d}: listo", flush=True)
        return ruta

    with ThreadPoolExecutor(simultaneos) as pool:
        rutas = [r for r in pool.map(bajar, _meses(desde, hasta)) if r is not None]
    return xr.open_mfdataset(rutas, combine="by_coords", decode_coords="all").ndvi


def serie_puntos(ndvi, puntos):
    """Serie de NDVI (tiempo x id) en cada punto (DataFrame con columnas id, lat, lon)."""
    import geopandas as gpd

    gdf = gpd.GeoDataFrame(puntos, geometry=gpd.points_from_xy(puntos.lon, puntos.lat), crs="EPSG:4326")
    gdf = gdf.to_crs(ndvi.rio.crs)
    # Mediana de una ventana de 3x3 pixeles (60 m) para reducir ruido
    suave = ndvi.rolling(x=3, y=3, center=True, min_periods=1).median()
    muestras = suave.sel(
        x=xr.DataArray(gdf.geometry.x.values, dims="id"),
        y=xr.DataArray(gdf.geometry.y.values, dims="id"),
        method="nearest",
    ).compute()
    return pd.DataFrame(muestras.values, index=pd.to_datetime(muestras.tiempo.values), columns=puntos.id.values)


def graficar(series, puntos, ruta, columnas=4):
    """Una gráfica pequeña por punto con su historia de NDVI."""
    n = len(puntos)
    filas = int(np.ceil(n / columnas))
    fig, ejes = plt.subplots(filas, columnas, figsize=(5 * columnas, 2.4 * filas), sharex=True, sharey=True)
    for ax, (_, p) in zip(ejes.flat, puntos.iterrows()):
        s = series[p.id].interpolate(limit=2)
        ax.plot(s.index, s.values, color="#2a7f62", lw=1.3)
        secas = s[s.index.month.isin([3, 4, 5])].groupby(s[s.index.month.isin([3, 4, 5])].index.year).median()
        ax.plot(pd.to_datetime([f"{a}-04-15" for a in secas.index]), secas.values, "o", color="#c0392b", ms=4)
        ax.set_title(f"Punto {p.id} · grupo {p.grupo}", fontsize=10)
        ax.set_ylim(-0.05, 0.95)
        ax.grid(alpha=0.3)
    for ax in list(ejes.flat)[n:]:
        ax.axis("off")
    fig.suptitle("Historia de verdor (NDVI) por punto · verde: mensual · rojo: mediana de secas (mar–may)", y=1.0)
    fig.tight_layout()
    fig.savefig(ruta, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zona", choices=sorted(ZONAS))
    p.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    p.add_argument("--desde", default="2018-01", help="AAAA-MM")
    p.add_argument("--hasta", help="AAAA-MM (por omisión el último mes completo)")
    p.add_argument("--resolucion", type=int, default=20)
    p.add_argument("--puntos", type=Path, help="CSV con columnas id, grupo, lat, lon")
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    if not args.zona and not args.bbox:
        p.error("indica --zona o --bbox")
    bbox = tuple(args.bbox) if args.bbox else ZONAS[args.zona]["bbox"]
    desde = tuple(int(v) for v in args.desde.split("-"))
    hasta = tuple(int(v) for v in args.hasta.split("-")) if args.hasta else datos.ultimos_12_meses()[-1]

    print(f"Descargando NDVI mensual {desde[0]}-{desde[1]:02d} a {hasta[0]}-{hasta[1]:02d}...")
    ndvi = descargar(bbox, desde, hasta, args.salida / "mensual", args.resolucion)
    if args.puntos:
        puntos = pd.read_csv(args.puntos)
        series = serie_puntos(ndvi, puntos)
        series.round(3).to_csv(args.salida / "ndvi_puntos.csv")
        graficar(series, puntos, args.salida / "historia_puntos.png")
        print(f"Listo: {args.salida}/historia_puntos.png")


if __name__ == "__main__":
    main()
