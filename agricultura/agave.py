"""Detección de agave y año de establecimiento con reglas de varios años.

El maíz repite su ciclo cada año (verdor alto en lluvias, bajo en secas). El agave
ocupa el predio 5–7 años: un año "valle" casi sin verdor (plantación), después el
verdor de la temporada seca sube año con año con poca diferencia entre lluvias y
secas, y una caída brusca en la jima. Los umbrales se ajustaron con puntos de
referencia verificados en Tequila–Amatitán (ver README).

Uso:
    python -m agricultura.agave --historico agricultura/resultados/tequila/historico/mensual \
        --zona tequila --salida agricultura/resultados/tequila/agave
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from . import datos
from .config import ZONAS

SECAS = [3, 4, 5]
LLUVIAS = [7, 8, 9, 10]

# Umbrales (NDVI)
VALLE = 0.25  # verdor de secas máximo en el año de plantación o jima
MARGEN_VALLE = 0.04  # el valle debe estar a esta distancia del mínimo del periodo
SUBIDA_MIN = 0.12  # cuánto debe subir el verdor de secas después del valle
SECAS_ESTABLECIDO = 0.28  # verdor de secas de un agave ya establecido
AMPLITUD_MAX_AGAVE = 0.40  # amplitud media (lluvias - secas) máxima del agave
CAIDA_JIMA = 0.10  # caída mínima desde el máximo para considerar jima
BOSQUE = 0.48  # verdor de secas mediano de bosque o vegetación densa
AMPLITUD_ANUAL = 0.33  # amplitud media de cultivos anuales / vegetación caducifolia
PENDIENTE_SELVA = 12  # grados; ciclo anual en laderas = selva baja caducifolia

CLASES = {
    0: "sin dato",
    1: "agua",
    2: "urbano / sin vegetación",
    3: "bosque / vegetación densa",
    4: "agave en pie",
    5: "agave cosechado (jima reciente)",
    6: "cultivo anual (maíz / temporal)",
    7: "selva baja caducifolia",
    8: "otro (pastizal, matorral, mixto)",
}


def _cuantil(valores, q):
    """Cuantil en el eje 0 ignorando NaN (mucho más rápido que np.nanquantile)."""
    orden = np.sort(valores, axis=0)  # los NaN quedan al final
    n = (~np.isnan(valores)).sum(0)
    pos = q * np.maximum(n - 1, 0)
    abajo = np.floor(pos).astype(int)
    arriba = np.minimum(abajo + 1, np.maximum(n - 1, 0))
    v_abajo = np.take_along_axis(orden, abajo[None], 0)[0]
    v_arriba = np.take_along_axis(orden, arriba[None], 0)[0]
    return np.where(n > 0, v_abajo + (pos - abajo) * (v_arriba - v_abajo), np.nan)


def metricas_anuales(ndvi):
    """Verdor de secas (mediana mar–may) y amplitud (p90 jul–oct menos secas) por año.

    `ndvi`: DataArray con dimensión `tiempo` mensual. Devuelve (secas, amplitud) con dimensión `anio`.
    """
    ndvi = ndvi.interpolate_na("tiempo", max_gap=np.timedelta64(70, "D"))
    otras = [d for d in ndvi.dims if d != "tiempo"]
    valores = ndvi.transpose("tiempo", *otras).values
    fechas = pd.DatetimeIndex(ndvi.tiempo.values)
    anios = np.unique(fechas.year)
    vacio = np.full(valores.shape[1:], np.nan, dtype="float32")
    secas, lluvias = [], []
    with np.errstate(all="ignore"):
        for anio in anios:
            en_secas = (fechas.year == anio) & fechas.month.isin(SECAS)
            en_lluvias = (fechas.year == anio) & fechas.month.isin(LLUVIAS)
            secas.append(np.nanmedian(valores[en_secas], 0) if en_secas.any() else vacio)
            lluvias.append(_cuantil(valores[en_lluvias], 0.9) if en_lluvias.any() else vacio)
    coords = {"anio": anios, **{d: ndvi[d] for d in otras if d in ndvi.coords}}
    secas = xr.DataArray(np.stack(secas), dims=("anio", *otras), coords=coords)
    lluvias = xr.DataArray(np.stack(lluvias), dims=("anio", *otras), coords=coords)
    return secas, lluvias - secas


def _ultimo(mascara):
    """Índice del último True en el eje 0, o -1."""
    rev = mascara[::-1]
    return np.where(rev.any(0), mascara.shape[0] - 1 - rev.argmax(0), -1)


def _primero(mascara):
    return np.where(mascara.any(0), mascara.argmax(0), -1)


def _en(arr, idx):
    return np.take_along_axis(arr, np.clip(idx, 0, None)[None], 0)[0]


def _ciclo(S, A, desde):
    """Busca el último valle desde el año `desde` y evalúa si después hay agave establecido."""
    anios = np.arange(S.shape[0])[:, None]
    en_periodo = anios >= desde
    with np.errstate(all="ignore"):
        minimo = np.nanmin(np.where(en_periodo, S, np.nan), 0)
        valle = _ultimo(en_periodo & (S < VALLE) & (S <= minimo + MARGEN_VALLE))
        despues = (anios > valle) & (valle >= 0)
        S_d = np.where(despues, S, np.nan)
        A_d = np.where(despues, A, np.nan)
        agave = (
            (valle >= 0)
            & (despues.sum(0) >= 2)
            & (np.nanmax(S_d, 0) - _en(S, valle) >= SUBIDA_MIN)
            & ((S_d >= SECAS_ESTABLECIDO).sum(0) >= 2)
            & (np.nanmean(A_d, 0) < AMPLITUD_MAX_AGAVE)
            & (np.nanmedian(S_d, 0) < BOSQUE)
        )
    return valle, agave, S_d


def clasificar(S, A, pendiente=None, ndvi_mediana=None):
    """Clasifica pixeles a partir de métricas anuales.

    `S`, `A`: arreglos (años, n) de verdor de secas y amplitud. `pendiente`: (n,) grados.
    `ndvi_mediana`: (n,) NDVI mediano de todos los meses (para agua).
    Devuelve dict con `clase` (n,), `establecimiento` y `jima` (índice de año o -1).
    """
    n_anios, n = S.shape
    clase = np.full(n, 8, dtype="uint8")
    with np.errstate(all="ignore"):
        S_med = np.nanmedian(S, 0)
        A_media = np.nanmean(A, 0)

    valle, agave, S_d = _ciclo(S, A, np.zeros(n, dtype=int))
    establecimiento = np.where(agave, valle, -1)
    jima = np.full(n, -1)

    # ¿El agave detectado ya se cosechó? Caída fuerte después de su máximo.
    with np.errstate(all="ignore"):
        maximo = np.nanmax(S_d, 0)
    anio_max = np.nanargmax(np.where(np.isnan(S_d), -np.inf, S_d), 0)
    anios = np.arange(n_anios)[:, None]
    caida = _primero((anios > anio_max) & (S < VALLE) & (S <= maximo - CAIDA_JIMA))
    cosechado = agave & (caida >= 0)
    # Si hubo jima, buscar un nuevo ciclo a partir de ese año
    valle2, agave2, _ = _ciclo(S, A, np.where(cosechado, caida, n_anios))
    replantado = cosechado & agave2
    jima = np.where(cosechado, caida, -1)
    establecimiento = np.where(replantado, valle2, np.where(cosechado, -1, establecimiento))

    clase[(A_media >= AMPLITUD_ANUAL) & (S_med < BOSQUE)] = 6
    if pendiente is not None:
        clase[(clase == 6) & (pendiente >= PENDIENTE_SELVA)] = 7
    clase[S_med >= BOSQUE] = 3
    clase[cosechado & ~replantado] = 5
    clase[establecimiento >= 0] = 4
    clase[(S_med < 0.25) & (A_media < 0.06)] = 2
    if ndvi_mediana is not None:
        clase[ndvi_mediana < 0.0] = 1
    clase[np.isnan(S).all(0)] = 0
    return {"clase": clase, "establecimiento": establecimiento, "jima": jima}


def _grafica(clase, establecimiento, anios, ruta):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(18, 7))
    colores = ["#ffffff", "#2b6cb0", "#7f7f7f", "#1e5631", "#5fa8a0", "#d4a017", "#e9d8a6", "#8fbc5a", "#c9b79c"]
    cmap = matplotlib.colors.ListedColormap(colores)
    a1.imshow(clase, cmap=cmap, vmin=-0.5, vmax=8.5, interpolation="nearest")
    a1.set_title("Uso del suelo (reglas de varios años)")
    a1.axis("off")
    a1.legend(
        handles=[matplotlib.patches.Patch(color=colores[k], label=v) for k, v in CLASES.items() if k > 0],
        loc="lower left", fontsize=8, framealpha=0.9,
    )
    edad = np.ma.masked_less(establecimiento.astype(float), 0)
    im = a2.imshow(np.ma.masked_where(edad.mask, np.take(anios, edad.filled(0).astype(int))),
                   cmap="viridis", interpolation="nearest")
    a2.set_title("Agave en pie: año de establecimiento")
    a2.axis("off")
    fig.colorbar(im, ax=a2, fraction=0.035)
    fig.tight_layout()
    fig.savefig(ruta, dpi=130)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--historico", type=Path, required=True, help="carpeta con ndvi_AAAA-MM.nc")
    p.add_argument("--zona", choices=sorted(ZONAS))
    p.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    if not args.zona and not args.bbox:
        p.error("indica --zona o --bbox")
    bbox = tuple(args.bbox) if args.bbox else ZONAS[args.zona]["bbox"]
    args.salida.mkdir(parents=True, exist_ok=True)

    ndvi = xr.open_mfdataset(sorted(args.historico.glob("ndvi_*.nc")), combine="by_coords",
                             decode_coords="all").ndvi.load()
    secas, amplitud = metricas_anuales(ndvi)
    anios = secas.anio.values
    plantilla = ndvi.isel(tiempo=0, drop=True)
    pendiente = datos.elevacion(bbox, plantilla).pendiente.values
    _, alto, ancho = secas.shape
    r = clasificar(
        secas.values.reshape(len(anios), -1),
        amplitud.values.reshape(len(anios), -1),
        pendiente.reshape(-1),
        ndvi.median("tiempo").values.reshape(-1),
    )

    clase = r["clase"].reshape(alto, ancho)
    est = r["establecimiento"].reshape(alto, ancho)
    jima = r["jima"].reshape(alto, ancho)
    a_anio = lambda idx: np.where(idx >= 0, anios[np.clip(idx, 0, None)], 0).astype("uint16")
    def exportar(valores, nombre):
        capa = xr.DataArray(valores, dims=("y", "x"), coords={"y": plantilla.y, "x": plantilla.x})
        capa.rio.write_crs(plantilla.rio.crs).rio.write_nodata(0).rio.to_raster(args.salida / nombre)

    exportar(clase, "uso_suelo.tif")
    exportar(a_anio(est), "agave_establecimiento.tif")
    exportar(a_anio(jima), "agave_jima.tif")

    res_x, res_y = plantilla.rio.resolution()
    ha = abs(res_x * res_y) / 10_000
    sup = pd.Series(clase.ravel()).value_counts().sort_index()
    tabla = pd.DataFrame({"clase": [CLASES[k] for k in sup.index], "hectareas": (sup.values * ha).round(0)})
    tabla = tabla[tabla.clase != "sin dato"]
    tabla.to_csv(args.salida / "superficie_uso_suelo.csv", index=False)
    por_anio = pd.Series(a_anio(est)[clase == 4]).value_counts().sort_index() * ha
    por_anio = por_anio.rename_axis("anio_establecimiento").rename("hectareas").round(0)
    por_anio.to_csv(args.salida / "agave_por_anio_establecimiento.csv")
    jimas = (pd.Series(a_anio(jima)[clase == 5]).value_counts().sort_index() * ha).round(0)
    jimas.rename_axis("anio_jima").rename("hectareas").round(0).to_csv(args.salida / "agave_jima_por_anio.csv")
    _grafica(clase, est, anios, args.salida / "agave.png")

    print(tabla.to_string(index=False))
    print("\nAgave en pie por año de establecimiento (ha):")
    print(por_anio.to_string())
    print("\nAgave cosechado sin replantar, por año de jima (ha):")
    print(jimas.to_string())


if __name__ == "__main__":
    main()
