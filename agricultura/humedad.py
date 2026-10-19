"""Filtro espectral del agave detectado: humedad de hoja en secas, tono en lluvias y predio compacto.

Las reglas de `agave.py` solo usan el NDVI, y lo que imita al agave (pastizal y monte en la
sierra, huertas en Michoacán) tiene un NDVI parecido. La penca suculenta guarda agua: en
secas el agave conserva humedad de hoja en el infrarrojo de onda corta, NDMI = (B08 − B11) /
(B08 + B11), mientras el pastizal y el monte están secos (`resultados/verificacion/imitadores/`).

Para un mosaico ya procesado baja solo unos meses (secas 2025 y 2026, septiembre 2025) con
las bandas azul, rojo, infrarrojo cercano e infrarrojo de onda corta, y marca cada pixel de
agave en pie con tres pruebas:
- humedad: NDMI de secas > 0.03 (el mayor de las medianas de 2025 y 2026);
- tono: azul / rojo de septiembre < 0.80 (la penca es azulada; la hoja ancha, no);
- compacto: al menos 60 % de agave en la ventana de 5 × 5 pixeles (100 m), como un predio
  y no pixeles sueltos de monte.

No cambia `uso_suelo.tif`: guarda las capas y una tabla por municipio con el agave antes y
después de cada prueba, para comparar contra el SIAP.

Uso:
    python -m agricultura.humedad --mosaico 13QGB
"""

import argparse
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr
from rasterio.features import rasterize
from scipy import ndimage

from . import datos
from .mosaico import ESCALA, SIN_DATO, rejilla
from .municipios import MUNICIPIOS, _area_propia

RAIZ = Path(__file__).parent
MOSAICOS = RAIZ / "resultados" / "mosaicos"
SECAS = {2025: [3, 4, 5], 2026: [3, 4, 5]}
LLUVIAS = (2025, 9)
AGAVE = 4
NDMI_MIN = 0.03
AZUL_ROJO_MAX = 0.80
COMPACTO_MIN = 0.6
VENTANA = 5


def compuesto(mosaico, anio, mes, geobox):
    """NDMI y azul/rojo medianos sin nubes del mes (int16 ×10000), o (None, None)."""
    import odc.stac

    items = datos.escenas_mosaicos([mosaico], anio, mes)
    if not items:
        return None, None
    ds = odc.stac.load(items, bands=["blue", "red", "nir", "swir16", "scl"], geobox=geobox, groupby="solar_day",
                       chunks={"x": 1830, "y": 1830}, resampling={"scl": "nearest", "*": "average"})
    offset_dia = {np.datetime64(i.datetime.replace(tzinfo=None), "D"): datos._offset(i) for i in items}
    offset = xr.DataArray([offset_dia.get(np.datetime64(t, "D"), 0) for t in ds.time.values], dims="time")
    valido = ds.scl.isin(datos.SCL_VALIDOS) & (ds.red > 0) & (ds.nir > 0) & (ds.swir16 > 0)
    b = {k: (ds[k].astype("float32") - offset).where(valido) for k in ("blue", "red", "nir", "swir16")}
    ndmi = ((b["nir"] - b["swir16"]) / (b["nir"] + b["swir16"])).median("time").compute().values
    azul_rojo = (b["blue"] / b["red"]).median("time").compute().values
    a_entero = lambda a: np.where(np.isfinite(a), np.round(np.clip(a, -3, 3) * ESCALA), SIN_DATO).astype("int16")
    return a_entero(ndmi), a_entero(azul_rojo)


def descargar(mosaico, carpeta, geobox, simultaneos=1):
    carpeta.mkdir(parents=True, exist_ok=True)
    meses = [(a, m) for a, ms in SECAS.items() for m in ms] + [LLUVIAS]

    def bajar(periodo):
        anio, mes = periodo
        ruta = carpeta / f"esp_{anio}-{mes:02d}.npz"
        if ruta.exists():
            return
        inicio = time.time()
        ndmi, azul_rojo = compuesto(mosaico, anio, mes, geobox)
        if ndmi is None:
            print(f"  {anio}-{mes:02d}: sin escenas", flush=True)
            return
        tmp = ruta.with_name("tmp_" + ruta.name)
        np.savez_compressed(tmp, ndmi=ndmi, azul_rojo=azul_rojo)
        tmp.replace(ruta)
        print(f"  {anio}-{mes:02d}: {time.time() - inicio:.0f} s", flush=True)

    with ThreadPoolExecutor(simultaneos) as pool:
        list(pool.map(bajar, meses))


def _leer(carpeta, anio, mes, campo):
    ruta = carpeta / f"esp_{anio}-{mes:02d}.npz"
    if not ruta.exists():
        return None
    a = np.load(ruta)[campo].astype("float32")
    a[a == SIN_DATO] = np.nan
    return a / ESCALA


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", required=True)
    p.add_argument("--conservar", action="store_true", help="no borrar los compuestos mensuales")
    args = p.parse_args(argv)
    m = MOSAICOS / args.mosaico
    uso = rioxarray.open_rasterio(m / "uso_suelo.tif").squeeze("band", drop=True)
    geobox = rejilla(args.mosaico)
    if geobox.shape != uso.shape:
        raise ValueError(f"La rejilla {geobox.shape} no coincide con uso_suelo {uso.shape}")
    carpeta = m / "humedad_mensual"
    print(f"Compuestos de {args.mosaico}...", flush=True)
    descargar(args.mosaico, carpeta, geobox)

    with np.errstate(all="ignore"):
        por_anio = []
        for anio, meses in SECAS.items():
            capas = [c for c in (_leer(carpeta, anio, mes, "ndmi") for mes in meses) if c is not None]
            if capas:
                por_anio.append(np.nanmedian(np.stack(capas), 0))
        ndmi = np.nanmax(np.stack(por_anio), 0)
        azul_rojo = _leer(carpeta, *LLUVIAS, "azul_rojo")

    agave = uso.values == AGAVE
    fraccion = ndimage.uniform_filter(agave.astype("float32"), size=VENTANA, mode="constant")
    humedo = agave & (ndmi > NDMI_MIN)
    azulado = humedo & (azul_rojo < AZUL_ROJO_MAX) if azul_rojo is not None else humedo
    compacto = humedo & (fraccion >= COMPACTO_MIN)
    todo = azulado & (fraccion >= COMPACTO_MIN)

    plantilla = uso.astype("int16")
    guardar = lambda a, nombre: plantilla.copy(data=np.where(np.isfinite(a), np.round(a * 1000), SIN_DATO).astype("int16")) \
        .rio.write_nodata(SIN_DATO).rio.to_raster(m / nombre, compress="deflate")
    guardar(np.where(agave, ndmi, np.nan), "agave_ndmi_secas.tif")
    if azul_rojo is not None:
        guardar(np.where(agave, azul_rojo, np.nan), "agave_azul_rojo_lluvias.tif")

    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=uso.shape,
                    transform=uso.rio.transform(), fill=0, dtype="int32")
    propio = _area_propia(uso) & (ids > 0)
    ha = abs(np.prod(uso.rio.resolution())) / 10_000
    cuenta = lambda masc: np.bincount(ids[masc & propio] - 1, minlength=len(mun)) * ha
    t = mun[["municipio", "estado", "denominacion_origen"]].copy()
    t["agave_ha"] = cuenta(agave)
    t["humedo_ha"] = cuenta(humedo)
    t["humedo_azulado_ha"] = cuenta(azulado)
    t["humedo_compacto_ha"] = cuenta(compacto)
    t["todas_ha"] = cuenta(todo)
    t = t[t.agave_ha > 0].round(0)
    t.to_csv(m / "filtro_espectral_por_municipio.csv", index=False)
    if not args.conservar:
        shutil.rmtree(carpeta, ignore_errors=True)
    tot = t[["agave_ha", "humedo_ha", "humedo_azulado_ha", "humedo_compacto_ha", "todas_ha"]].sum()
    print((tot / tot.agave_ha * 100).round(0).to_string())
    print(t.sort_values("agave_ha", ascending=False).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
