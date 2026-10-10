"""Resumen y mapa de una región (grupo de municipios) a partir de los mosaicos procesados.

Une los mapas de los mosaicos, recorta a los municipios de la región y genera:
tabla por municipio, calendario de agave que llega a edad de jima y mapa.

Uso:
    python -m agricultura.region --nombre valles --salida agricultura/resultados/regiones/valles
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray
from rioxarray.merge import merge_arrays

from .municipios import MUNICIPIOS

RAIZ = Path(__file__).parent
REGIONES = {
    # Región Valles de Jalisco (regionalización oficial del estado)
    "valles": ["Ahualulco de Mercado", "Amatitán", "Ameca", "San Juanito de Escobedo", "El Arenal", "Etzatlán",
               "Hostotipaquillo", "Magdalena", "San Marcos", "San Martín Hidalgo", "Tala", "Tequila",
               "Teuchitlán", "Cocula"],
}
EDAD_JIMA = (6, 7)  # años desde el establecimiento


def mapa_region(mosaicos, municipios, ruta, titulo):
    capas = {n: [rioxarray.open_rasterio(m / f"{n}.tif").squeeze("band", drop=True) for m in mosaicos]
             for n in ("uso_suelo", "agave_establecimiento")}
    mun = municipios.to_crs(capas["uso_suelo"][0].rio.crs)
    x0, y0, x1, y1 = mun.total_bounds
    uniones = {}
    for n, lista in capas.items():
        recortes = [c.rio.clip_box(x0, y0, x1, y1) for c in lista
                    if c.rio.bounds()[0] < x1 and c.rio.bounds()[2] > x0 and c.rio.bounds()[1] < y1 and c.rio.bounds()[3] > y0]
        uniones[n] = merge_arrays(recortes, nodata=0) if len(recortes) > 1 else recortes[0]
    est = uniones["agave_establecimiento"].rio.clip(mun.geometry, drop=False).values.astype(float)
    uso = uniones["uso_suelo"].rio.clip(mun.geometry, drop=False).values
    est[est == 0] = np.nan
    ext = list(uniones["uso_suelo"].rio.bounds())
    ext = [ext[0], ext[2], ext[1], ext[3]]

    fig, ax = plt.subplots(figsize=(12, 11))
    fondo = np.where(uso > 0, 1.0, np.nan)
    ax.imshow(fondo, cmap=matplotlib.colors.ListedColormap(["#e4e7e3"]), extent=ext, interpolation="nearest")
    im = ax.imshow(est, cmap="viridis", vmin=2018, vmax=2024, extent=ext, interpolation="nearest")
    mun.boundary.plot(ax=ax, color="#333", lw=0.7)
    for _, r in mun.iterrows():
        p = r.geometry.representative_point()
        ax.text(p.x, p.y, r.municipio, fontsize=9, ha="center", va="center",
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.75})
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    ax.set_title(titulo)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("Año de establecimiento del agave en pie")
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nombre", choices=sorted(REGIONES), required=True)
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)
    nombres = REGIONES[args.nombre]

    agave = pd.read_csv(RAIZ / "resultados" / "municipios" / "agave_por_municipio_y_anio.csv")
    jima = pd.read_csv(RAIZ / "resultados" / "municipios" / "jima_por_municipio.csv")
    agave = agave[(agave.estado == "Jalisco") & agave.municipio.isin(nombres)]
    jima = jima[(jima.estado == "Jalisco") & jima.municipio.isin(nombres)]
    faltan = sorted(set(nombres) - set(agave.municipio))
    tabla = agave.merge(jima.drop(columns=["estado", "denominacion_origen", "area_ha", "cobertura_pct"],
                                  errors="ignore"), on="municipio", how="left").fillna(0)
    tabla.to_csv(args.salida / "municipios.csv", index=False)

    col_plant = sorted(c for c in tabla.columns if c.startswith("plantado_"))
    plantado = tabla[col_plant].sum().rename(lambda c: int(c.split("_")[1]))
    calendario = {}
    for anio_est, ha in plantado.items():
        for edad in EDAD_JIMA:
            calendario[anio_est + edad] = calendario.get(anio_est + edad, 0) + ha / len(EDAD_JIMA)
    calendario = pd.Series(calendario).sort_index().round(0)

    resumen = {
        "region": args.nombre,
        "municipios_con_datos": int(len(tabla)),
        "municipios_sin_datos": faltan,
        "agave_en_pie_ha": float(tabla.agave_en_pie_ha.sum()),
        "plantado_por_anio": {int(k): float(v) for k, v in plantado.items()},
        "llega_a_jima_por_anio": {int(k): float(v) for k, v in calendario.items()},
        "jima_reciente_ha": {c: float(tabla[c].sum()) for c in tabla.columns if c.startswith("jima_")},
    }
    (args.salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))

    mosaicos = sorted(m for m in (RAIZ / "resultados" / "mosaicos").iterdir() if (m / "uso_suelo.tif").exists())
    mun = gpd.read_file(MUNICIPIOS)
    mun = mun[(mun.estado == "Jalisco") & mun.municipio.isin(nombres)]
    mapa_region(mosaicos, mun, args.salida / "mapa.png", f"Región {args.nombre.title()}: agave en pie por año de establecimiento")
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    print(tabla[["municipio", "cobertura_pct", "agave_en_pie_ha"] + col_plant].to_string(index=False))


if __name__ == "__main__":
    main()
