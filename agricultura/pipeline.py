"""Flujo completo: descarga de imágenes -> características -> mapa de cultivos.

Uso:
    python -m agricultura.pipeline --zona tequila --salida resultados/tequila
    python -m agricultura.pipeline --zona tequila --etiquetas predios.geojson --salida ...

Usa los 12 meses completos más recientes (o los que terminan en --hasta AAAA-MM).

Sin `--etiquetas` hace un agrupamiento por calendario de verdor (patrones de uso del
suelo). Con etiquetas entrena el clasificador y produce el mapa de cultivos.
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from . import caracteristicas, datos, etiquetas, modelo
from .config import ZONAS


def descargar(bbox, periodos, resolucion, carpeta):
    """Descarga (o reutiliza) los compuestos mensuales y la elevación."""
    (a0, m0), (a1, m1) = periodos[0], periodos[-1]
    ruta_s2 = carpeta / f"s2_mensual_{a0}-{m0:02d}_{a1}-{m1:02d}.nc"
    ruta_dem = carpeta / "elevacion.nc"
    if ruta_s2.exists():
        s2 = xr.open_dataset(ruta_s2, decode_coords="all").load()
    else:
        print(f"Descargando Sentinel-2 {a0}-{m0:02d} a {a1}-{m1:02d}...")
        s2 = datos.compuesto_mensual_s2(bbox, periodos, resolucion)
        s2.to_netcdf(ruta_s2)
    if ruta_dem.exists():
        dem = xr.open_dataset(ruta_dem, decode_coords="all").load()
    else:
        print("Descargando elevación...")
        dem = datos.elevacion(bbox, s2.B04.isel(mes=0))
        dem.to_netcdf(ruta_dem)
    return s2, dem


def guardar_rgb(s2, carpeta):
    """Color verdadero (temporada seca) como PNG y GeoTIFF, para revisar y etiquetar en QGIS."""
    rgb = s2[["B04", "B03", "B02"]].sel(mes=datos_secos(s2)).median("mes").to_array("banda")
    rgb.rio.to_raster(carpeta / "color_verdadero.tif")
    img = np.clip(rgb.transpose("y", "x", "banda").values / 0.25, 0, 1)
    plt.imsave(carpeta / "color_verdadero.png", np.nan_to_num(img))


def datos_secos(s2):
    return [m for m in caracteristicas.SECAS if m in s2.mes.values]


def graficar_grupos(grupo, centros, anios_por_mes, carpeta):
    """Mapa de grupos y curva anual de NDVI de cada grupo."""
    n = len(centros)
    colores = plt.get_cmap("tab20", n)
    fig, (ax_mapa, ax_curvas) = plt.subplots(1, 2, figsize=(18, 7), gridspec_kw={"width_ratios": [1.3, 1]})
    mapa = np.ma.masked_equal(grupo.values, 0)
    ax_mapa.imshow(mapa, cmap=colores, vmin=0.5, vmax=n + 0.5, interpolation="nearest")
    ax_mapa.set_title("Grupos por calendario de verdor")
    ax_mapa.axis("off")

    # Orden cronológico (p. ej. oct 2025 -> sep 2026)
    anios = dict(zip(range(1, 13), anios_por_mes))
    orden = sorted(anios, key=lambda m: (anios[m], m))
    cols_ndvi = [f"ndvi_m{m:02d}" for m in orden]
    total = (grupo.values > 0).sum()
    for g, fila in centros.iterrows():
        pct = 100 * (grupo.values == g).sum() / total
        ax_curvas.plot(range(12), fila[cols_ndvi], color=colores(g - 1), lw=2, label=f"Grupo {g} ({pct:.0f}%)")
    letras = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    ax_curvas.set_xticks(range(12), [f"{letras[m - 1]}\n{str(anios[m])[2:]}" for m in orden])
    ax_curvas.set_ylabel("NDVI (verdor)")
    ax_curvas.set_title("Verdor mensual promedio de cada grupo")
    ax_curvas.grid(alpha=0.3)
    ax_curvas.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(carpeta / "grupos.png", dpi=130)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zona", choices=sorted(ZONAS), help="zona piloto predefinida")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    p.add_argument("--hasta", help="último mes a usar, AAAA-MM (por omisión el último mes completo)")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--resolucion", type=int, default=10, help="metros por pixel (10 o 20)")
    p.add_argument("--etiquetas", type=Path, help="GeoJSON/GPKG con campo `clase`")
    p.add_argument("--grupos", type=int, default=12, help="número de grupos sin etiquetas")
    args = p.parse_args(argv)
    if not args.zona and not args.bbox:
        p.error("indica --zona o --bbox")
    bbox = tuple(args.bbox) if args.bbox else ZONAS[args.zona]["bbox"]
    args.salida.mkdir(parents=True, exist_ok=True)

    hasta = tuple(int(v) for v in args.hasta.split("-")) if args.hasta else None
    periodos = datos.ultimos_12_meses(hasta)
    s2, dem = descargar(bbox, periodos, args.resolucion, args.salida)
    guardar_rgb(s2, args.salida)
    print("Calculando características...")
    pila = caracteristicas.construir(s2, dem)
    print(f"  {pila.sizes['caracteristica']} características, {pila.sizes['y']}x{pila.sizes['x']} pixeles")

    if args.etiquetas is None:
        print("Agrupando por calendario de verdor...")
        grupo, centros = modelo.agrupar(pila, args.grupos)
        grupo.rio.to_raster(args.salida / "grupos.tif")
        centros.round(3).to_csv(args.salida / "grupos_ndvi_mensual.csv")
        graficar_grupos(grupo, centros, s2.anio.values, args.salida)
        print(f"Listo: {args.salida}/grupos.png, grupos.tif, color_verdadero.tif")
        return

    gdf = etiquetas.leer(args.etiquetas)
    X, y, grupos = etiquetas.muestrear(pila, gdf)
    paquete, reporte = modelo.entrenar(X, y, grupos, pila.caracteristica.values)
    print(reporte)
    (args.salida / "reporte.txt").write_text(reporte)
    modelo.guardar(paquete, args.salida / "modelo.joblib")
    clase, prob = modelo.predecir(paquete, pila)
    clase.rio.to_raster(args.salida / "cultivos.tif")
    prob.rio.to_raster(args.salida / "probabilidad.tif")
    tabla = modelo.superficie(clase)
    tabla.to_csv(args.salida / "superficie.csv", index=False)
    print(tabla.to_string(index=False))


if __name__ == "__main__":
    main()
