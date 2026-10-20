"""Filtro espectral del agave detectado: humedad de hoja en secas, tono en lluvias y predio compacto.

Las reglas de `agave.py` solo usan el NDVI, y lo que imita al agave (pastizal y monte en la
sierra, huertas en Michoacán) tiene un NDVI parecido. La penca suculenta guarda agua: en
secas el agave conserva humedad de hoja en el infrarrojo de onda corta, NDMI = (B08 − B11) /
(B08 + B11), mientras el pastizal y el monte están secos (`resultados/verificacion/imitadores/`).

Para un mosaico ya procesado baja solo tres meses (abril 2025, abril 2026 y septiembre
2025) con las 10 bandas de Sentinel-2, y marca cada pixel de agave en pie con tres pruebas:
- humedad: NDMI de abril > 0.03 (el mayor de 2025 y 2026);
- tono: azul / rojo de septiembre < 0.80 (la penca es azulada; la hoja ancha, no);
- compacto: al menos 60 % de agave en la ventana de 5 × 5 pixeles (100 m), como un predio
  y no pixeles sueltos de monte.

No cambia `uso_suelo.tif`: guarda las capas y una tabla por municipio con el agave antes y
después de cada prueba, para comparar contra el SIAP. Además guarda una muestra de pixeles
con las 10 bandas de los tres meses (`espectro_muestra.csv.gz`: hasta 10 mil de agave y 2 mil
de cada otra clase) para probar otras combinaciones de bandas o un clasificador sin volver
a bajar imágenes.

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
MESES = [(2025, 4), (2026, 4), (2025, 9)]
SECAS = [(2025, 4), (2026, 4)]
LLUVIAS = (2025, 9)
BANDAS = datos.ASSETS_S2  # asset -> B02...B12
MUESTRA_AGAVE = 10_000
MUESTRA_OTRAS = 2_000
AGAVE = 4
NDMI_MIN = 0.03
AZUL_ROJO_MAX = 0.80
COMPACTO_MIN = 0.6
VENTANA = 5


def compuesto(mosaico, anio, mes, geobox):
    """Reflectancia mediana sin nubes del mes por banda (dict banda -> int16 ×10000), o None."""
    import odc.stac

    items = datos.escenas_mosaicos([mosaico], anio, mes)
    if not items:
        return None
    ds = odc.stac.load(items, bands=list(BANDAS) + ["scl"], geobox=geobox, groupby="solar_day",
                       chunks={"x": 1830, "y": 1830}, resampling={"scl": "nearest", "*": "average"},
                       fail_on_error=False)  # una escena ilegible se salta en vez de tumbar el mosaico
    offset_dia = {np.datetime64(i.datetime.replace(tzinfo=None), "D"): datos._offset(i) for i in items}
    offset = xr.DataArray([offset_dia.get(np.datetime64(t, "D"), 0) for t in ds.time.values], dims="time")
    valido = ds.scl.isin(datos.SCL_VALIDOS) & (ds.red > 0) & (ds.nir > 0) & (ds.swir16 > 0)
    salida = {}
    for asset, banda in BANDAS.items():
        med = (ds[asset].astype("float32") - offset).where(valido).median("time").compute().values
        salida[banda] = np.where(np.isfinite(med), np.clip(np.round(med), -32767, 32767), SIN_DATO).astype("int16")
    return salida


def descargar(mosaico, carpeta, geobox, simultaneos=1):
    carpeta.mkdir(parents=True, exist_ok=True)

    def bajar(periodo):
        anio, mes = periodo
        ruta = carpeta / f"bandas_{anio}-{mes:02d}.npz"
        if ruta.exists():
            return
        inicio = time.time()
        b = compuesto(mosaico, anio, mes, geobox)
        if b is None:
            print(f"  {anio}-{mes:02d}: sin escenas", flush=True)
            return
        tmp = ruta.with_name("tmp_" + ruta.name)
        np.savez_compressed(tmp, **b)
        tmp.replace(ruta)
        print(f"  {anio}-{mes:02d}: {time.time() - inicio:.0f} s", flush=True)

    with ThreadPoolExecutor(simultaneos) as pool:
        list(pool.map(bajar, MESES))


def _bandas(carpeta, anio, mes):
    ruta = carpeta / f"bandas_{anio}-{mes:02d}.npz"
    if not ruta.exists():
        return None
    z = np.load(ruta)
    out = {}
    for b in z.files:
        a = z[b].astype("float32")
        a[z[b] == SIN_DATO] = np.nan
        out[b] = a / ESCALA
    return out


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

    meses = {f"{a}-{m:02d}": _bandas(carpeta, a, m) for a, m in MESES}
    with np.errstate(all="ignore"):
        nd = lambda b: (b["B08"] - b["B11"]) / (b["B08"] + b["B11"])
        ndmi = np.nanmax(np.stack([nd(meses[f"{a}-{m:02d}"]) for a, m in SECAS if meses[f"{a}-{m:02d}"]]), 0)
        lluvia = meses[f"{LLUVIAS[0]}-{LLUVIAS[1]:02d}"]
        azul_rojo = lluvia["B02"] / lluvia["B04"] if lluvia else None

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

    # Muestra de pixeles con las 10 bandas de los tres meses, para explorar otras combinaciones
    rng = np.random.default_rng(0)
    clases = uso.values
    filas = []
    for c in np.unique(clases[propio]):
        if c == 0:
            continue
        fy, fx = np.nonzero((clases == c) & propio)
        n = MUESTRA_AGAVE if c == AGAVE else MUESTRA_OTRAS
        k = rng.choice(len(fy), min(n, len(fy)), replace=False)
        filas.append((c, fy[k], fx[k]))
    est = rioxarray.open_rasterio(m / "agave_establecimiento.tif").squeeze("band", drop=True).values
    conf = rioxarray.open_rasterio(m / "agave_confianza.tif").squeeze("band", drop=True).values \
        if (m / "agave_confianza.tif").exists() else np.zeros_like(est)
    cs = np.concatenate([np.full(len(f[1]), f[0]) for f in filas])
    fy = np.concatenate([f[1] for f in filas]); fx = np.concatenate([f[2] for f in filas])
    mu = pd.DataFrame({"mosaico": args.mosaico, "clase": cs, "municipio": mun.municipio.values[ids[fy, fx] - 1],
                       "estado": mun.estado.values[ids[fy, fx] - 1], "x": uso.x.values[fx], "y": uso.y.values[fy],
                       "establecimiento": est[fy, fx], "confianza": conf[fy, fx],
                       "compacto": fraccion[fy, fx].round(2)})
    for mes, b in meses.items():
        if b:
            for banda, a in b.items():
                mu[f"{banda}_{mes}"] = (a[fy, fx] * ESCALA).round()
    mu.to_csv(m / "espectro_muestra.csv.gz", index=False)
    t.to_csv(m / "filtro_espectral_por_municipio.csv", index=False)
    if not args.conservar:
        shutil.rmtree(carpeta, ignore_errors=True)
    tot = t[["agave_ha", "humedo_ha", "humedo_azulado_ha", "humedo_compacto_ha", "todas_ha"]].sum()
    print((tot / tot.agave_ha * 100).round(0).to_string())
    print(t.sort_values("agave_ha", ascending=False).head(12).to_string(index=False))


if __name__ == "__main__":
    main()
