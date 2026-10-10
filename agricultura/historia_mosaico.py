"""Historia de plantación de agave de un mosaico completo: Landsat (1993–2017) + Sentinel-2 (2018–2026).

Une las métricas anuales de Landsat (calculadas aquí desde los NDVI mensuales de
`landsat.py --comprimido`) con las de Sentinel-2 que dejó `mosaico.py`
(`metricas_anuales.npz`, promediadas a la rejilla de 30 m de Landsat). Sobre la serie
de 30+ años detecta todos los años de plantación de cada pixel (`agave.plantaciones`)
y los resume por municipio, contando solo el cuadro de 100 km propio del mosaico.

Uso:
    python -m agricultura.historia_mosaico --mosaico agricultura/resultados/mosaicos/13QFD
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from . import agave
from .municipios import LADO_PROPIO, MUNICIPIOS

AMPLITUD_LANDSAT = 1.15  # Landsat TOA subestima la amplitud ~15 % frente a Sentinel-2 (calibrado en 2018–2021)
SIN_DATO = -32768
CULTIVO_ANUAL = 6  # clase de referencia estable para homologar años (campos de temporal en secas)


def _entero(a):
    return np.where(np.isfinite(a), np.round(a * 10000), SIN_DATO).astype("int16")


def _flotante(a):
    f = a.astype("float32")
    f[a == SIN_DATO] = np.nan
    return f / 10000


def metricas_landsat(carpeta, filas=400):
    """Secas y amplitud por año desde los NDVI mensuales comprimidos. Devuelve (anios, secas, amp, x, y, crs)."""
    archivos = {(int(p.stem[5:9]), int(p.stem[10:12])): p for p in carpeta.glob("ndvi_*.npz")}
    muestra = np.load(next(iter(archivos.values())))
    x, y, crs = muestra["x"], muestra["y"], str(muestra["crs"])
    anios = sorted({a for a, _ in archivos})
    secas = np.full((len(anios), len(y), len(x)), SIN_DATO, "int16")
    amp = np.full_like(secas, SIN_DATO)
    for i, anio in enumerate(anios):
        def pila(meses):
            capas = [np.load(archivos[(anio, m)])["ndvi"] for m in meses if (anio, m) in archivos]
            return np.stack(capas) if capas else None

        s, ll = pila(agave.SECAS), pila(agave.LLUVIAS)
        if s is None or ll is None:
            continue
        with np.errstate(all="ignore"):
            for f in range(0, len(y), filas):
                b = slice(f, f + filas)
                sv = np.nanmedian(_flotante(s[:, b]), 0)
                lv = agave._cuantil(_flotante(ll[:, b]), 0.9)
                secas[i, b] = _entero(sv)
                amp[i, b] = _entero((lv - sv) * AMPLITUD_LANDSAT)
        print(f"  Landsat {anio}: listo", flush=True)
    return anios, secas, amp, x, y, crs


def s2_a_rejilla(npz, x, y, crs):
    """Métricas anuales de Sentinel-2 (20 m) promediadas a la rejilla de Landsat (30 m)."""
    z = np.load(npz)
    sx, sy = z["x"], z["y"]
    res_s = float(sx[1] - sx[0])
    t_src = from_origin(sx[0] - res_s / 2, sy[0] + res_s / 2, res_s, res_s)
    res_l = float(x[1] - x[0])
    t_dst = from_origin(x[0] - res_l / 2, y[0] + res_l / 2, res_l, res_l)
    salida = {}
    for nombre in ("secas", "amplitud"):
        src = _flotante(z[nombre])
        dst = np.full((src.shape[0], len(y), len(x)), np.nan, "float32")
        for i in range(src.shape[0]):
            reproject(src[i], dst[i], src_transform=t_src, src_crs=CRS.from_wkt(str(z["crs"])),
                      dst_transform=t_dst, dst_crs=CRS.from_user_input(crs), resampling=Resampling.average,
                      src_nodata=np.nan, dst_nodata=np.nan)
        salida[nombre] = _entero(dst)
    return list(z["anios"]), salida["secas"], salida["amplitud"], (sx[0] - res_s / 2, sy[0] + res_s / 2)


def homologar(secas, amp, anios, referencia, anios_ref):
    """Ajusta cada año para que los campos de cultivo anual tengan el nivel de los años de referencia.

    Corrige saltos entre sensores (Landsat 5/7 contra 8, Landsat contra Sentinel-2) y
    años muy secos o lluviosos: verdor de secas con un desplazamiento aditivo y amplitud
    con un factor, ambos calculados con la mediana de los pixeles de referencia.
    """
    ref = referencia[::3, ::3]
    med = lambda a: np.nanmedian(_flotante(a[::3, ::3])[ref])
    en_ref = [i for i, a in enumerate(anios) if a in anios_ref]
    s_ref = np.nanmedian([med(secas[i]) for i in en_ref])
    a_ref = np.nanmedian([med(amp[i]) for i in en_ref])
    ajustes = []
    for i, a in enumerate(anios):
        if a in anios_ref:
            continue
        ds, fa = s_ref - med(secas[i]), a_ref / med(amp[i])
        if not (np.isfinite(ds) and np.isfinite(fa)):
            continue
        s = _flotante(secas[i]) + ds
        secas[i] = _entero(s)
        amp[i] = _entero(_flotante(amp[i]) * fa)
        ajustes.append((int(a), round(float(ds), 3), round(float(fa), 2)))
    return ajustes


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", type=Path, required=True, help="carpeta del mosaico (con landsat_mensual/ y metricas_anuales.npz)")
    p.add_argument("--hasta-landsat", type=int, default=2017)
    args = p.parse_args(argv)
    m = args.mosaico

    print("Métricas anuales de Landsat...", flush=True)
    al, sl, aml, x, y, crs = metricas_landsat(m / "landsat_mensual")
    keep = [i for i, a in enumerate(al) if a <= args.hasta_landsat]
    al, sl, aml = [al[i] for i in keep], sl[keep], aml[keep]
    print("Sentinel-2 a 30 m...", flush=True)
    a2, s2, am2, (x0_s2, ytop_s2) = s2_a_rejilla(m / "metricas_anuales.npz", x, y, crs)
    anios = np.array(al + a2)
    secas = np.concatenate([sl, s2])
    amp = np.concatenate([aml, am2])
    del sl, aml, s2, am2

    import rioxarray
    uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
    res = float(x[1] - x[0])
    clase = np.zeros((len(y), len(x)), "uint8")
    reproject(uso.values, clase, src_transform=uso.rio.transform(), src_crs=uso.rio.crs,
              dst_transform=from_origin(x[0] - res / 2, y[0] + res / 2, res, res),
              dst_crs=CRS.from_user_input(crs), resampling=Resampling.nearest)
    ajustes = homologar(secas, amp, anios, clase == CULTIVO_ANUAL, set(a2))
    pd.DataFrame(ajustes, columns=["anio", "desplazamiento_secas", "factor_amplitud"]).to_csv(
        m / "homologacion_landsat.csv", index=False)
    print("Ajustes por año (año, +secas, ×amplitud):", ajustes, flush=True)

    print("Detectando plantaciones...", flush=True)
    alto, ancho = len(y), len(x)
    evento = np.zeros((len(anios), alto, ancho), bool)
    for f in range(0, alto, 300):
        b = slice(f, f + 300)
        n = secas[:, b].shape[1] * ancho
        evento[:, b] = agave.plantaciones(_flotante(secas[:, b]).reshape(len(anios), n),
                                          _flotante(amp[:, b]).reshape(len(anios), n)).reshape(len(anios), -1, ancho)

    # Solo el cuadro propio de 100 km del mosaico (para no contar dos veces al unir mosaicos)
    propio = (y[:, None] > ytop_s2 - LADO_PROPIO) & (x[None, :] < x0_s2 + LADO_PROPIO)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    ids = rasterize(zip(mun.to_crs(crs).geometry, mun.index + 1), out_shape=(alto, ancho),
                    transform=from_origin(x[0] - res / 2, y[0] + res / 2, res, res), fill=0, dtype="int32")
    ha = res * res / 10_000
    filas = []
    for i, anio in enumerate(anios):
        sel = evento[i] & propio & (ids > 0)
        conteo = np.bincount(ids[sel] - 1, minlength=len(mun)) * ha
        filas.append(pd.Series(conteo, name=int(anio)))
    tabla = pd.concat(filas, axis=1).round(0)
    tabla = mun[["municipio", "estado", "denominacion_origen"]].join(tabla)
    tabla = tabla[tabla.iloc[:, 3:].sum(1) > 0]
    tabla.to_csv(m / "plantacion_historica_por_municipio.csv", index=False)
    total = tabla.iloc[:, 3:].sum().rename("hectareas_plantadas")
    total.index.name = "anio"
    total.to_csv(m / "plantacion_historica_total.csv")
    print(total.to_string())


if __name__ == "__main__":
    main()
