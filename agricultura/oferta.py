"""Oferta futura de agave maduro por municipio y año, a partir del año de plantación.

Cada pixel de agave en pie tiene su año de plantación (2018–2024). El agave azul se jima
normalmente entre los 6 y 7 años (antes si el precio sube). Para cada año calendario se
cuenta cuántas hectáreas cumplen 5, 6 y 7 años, por municipio y nivel de confianza, y se
convierten a toneladas con el rendimiento del SIAP (toneladas por hectárea cosechada,
2019–2025; del municipio si cosechó al menos 200 ha en esos años, si no del estado).

Límites:
- Tamaulipas queda fuera de los totales (las reglas no están calibradas para esa región).
- Solo cuenta lo plantado de 2018 a 2024: el agave plantado antes ya estaba establecido al
  inicio de la serie de Sentinel-2 y no se fecha (casi todo debió jimarse antes de 2025).
- Lo plantado en 2025–2026 todavía no se puede confirmar (hacen falta dos años de
  crecimiento), así que la oferta de 2031 en adelante está incompleta.

Uso:
    python -m agricultura.oferta --mosaicos agricultura/resultados/mosaicos \
        --salida agricultura/resultados/municipios
"""

import argparse
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
from rasterio.features import rasterize

from .municipios import MUNICIPIOS, _area_propia

RAIZ = Path(__file__).parent
SIAP = RAIZ / "datos_externos" / "siap_agave_municipal.csv"
AGAVE = 4
EDAD_JIMA = (6, 7)
COSECHADA_MIN = 200  # ha cosechadas 2019–2025 para usar el rendimiento del municipio
NIVELES = {1: "baja", 2: "media", 3: "alta"}
# Estados fuera de los totales: las reglas, calibradas en Jalisco, detectan ~67 veces el agave
# del SIAP en Tamaulipas (caña, cítricos, matorral). Siguen en la tabla por municipio.
SIN_CALIBRAR = {"Tamaulipas"}


def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return t.replace(" de ocampo", "").strip()


def rendimientos():
    """Toneladas por hectárea cosechada: {(estado, municipio): t/ha} y {estado: t/ha}."""
    s = pd.read_csv(SIAP)
    s = s[s.Anio >= 2019].assign(estado=lambda d: d.Nomestado.map(_norm), municipio=lambda d: d.Nommunicipio.map(_norm))
    e = s.groupby("estado")[["Volumenproduccion", "Cosechada"]].sum()
    m = s.groupby(["estado", "municipio"])[["Volumenproduccion", "Cosechada"]].sum()
    m = m[m.Cosechada >= COSECHADA_MIN]
    return (m.Volumenproduccion / m.Cosechada).to_dict(), (e.Volumenproduccion / e.Cosechada).to_dict()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaicos", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    partes = []
    for m in sorted(c for c in args.mosaicos.iterdir() if (c / "agave_confianza.tif").exists()):
        uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
        est = rioxarray.open_rasterio(m / "agave_establecimiento.tif").squeeze("band", drop=True).values
        conf = rioxarray.open_rasterio(m / "agave_confianza.tif").squeeze("band", drop=True).values
        ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=est.shape,
                        transform=uso.rio.transform(), fill=0, dtype="int32")
        sel = _area_propia(uso) & (ids > 0) & (uso.values == AGAVE) & (est > 0) & (conf > 0)
        ha = abs(np.prod(uso.rio.resolution())) / 10_000
        partes.append(pd.DataFrame({"mun": ids[sel] - 1, "plantacion": est[sel].astype(int), "nivel": conf[sel]})
                      .value_counts().mul(ha))
        print(f"{m.name}: listo", flush=True)

    t = pd.concat(partes).groupby(level=[0, 1, 2]).sum().unstack(fill_value=0).rename(columns=NIVELES)
    for n in NIVELES.values():
        if n not in t:
            t[n] = 0.0
    t = t.reset_index()
    t["alta_media"] = t.alta + t.media
    t["todo"] = t.alta_media + t.baja
    t = mun[["municipio", "estado", "denominacion_origen"]].join(t.set_index("mun"), how="inner").reset_index(drop=True)

    rend_mun, rend_edo = rendimientos()
    clave = list(zip(t.estado.map(_norm), t.municipio.map(_norm)))
    t["rend_t_ha"] = [rend_mun.get(k, rend_edo.get(k[0], np.nan)) for k in clave]
    t["rend_fuente"] = ["municipio" if k in rend_mun else "estado" for k in clave]

    filas = []
    for anio in range(2024, 2032):
        edad = anio - t.plantacion
        for e in (5, 6, 7):
            g = t[edad == e]
            if g.empty:
                continue
            filas.append(g.assign(anio=anio, edad=e)[["municipio", "estado", "denominacion_origen", "anio", "edad",
                                                      "alta", "alta_media", "todo", "rend_t_ha", "rend_fuente"]])
    o = pd.concat(filas)
    o = o.groupby(["municipio", "estado", "denominacion_origen", "anio", "edad", "rend_t_ha", "rend_fuente"],
                  dropna=False)[["alta", "alta_media", "todo"]].sum().reset_index()
    o["ton_alta_media"] = (o.alta_media * o.rend_t_ha).round(0)
    o[["alta", "alta_media", "todo"]] = o[["alta", "alta_media", "todo"]].round(0)
    o.sort_values(["estado", "municipio", "anio", "edad"]).to_csv(
        args.salida / "oferta_agave_maduro_por_municipio.csv", index=False)

    # Total: hectáreas que cumplen 6 años (edad típica de jima) cada año, y toneladas
    seis = o[(o.edad == 6) & ~o.estado.isin(SIN_CALIBRAR)].groupby("anio")[["alta", "alta_media", "todo", "ton_alta_media"]].sum()
    seis.to_csv(args.salida / "oferta_agave_maduro_total.csv")
    print(f"Agave que cumple 6 años (ha) y toneladas (alta+media), sin {', '.join(sorted(SIN_CALIBRAR))}:")
    print(seis.to_string())
    do = o[(o.edad == 6) & (o.denominacion_origen == "si")].groupby(["estado", "anio"]).alta_media.sum().unstack().round(0)
    print(do.to_string())


if __name__ == "__main__":
    main()
