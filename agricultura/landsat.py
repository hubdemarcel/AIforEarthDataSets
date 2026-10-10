"""NDVI mensual histórico con Landsat 5, 7 y 8 (1984–2021) desde Google Cloud.

Lee el archivo público `gcp-public-data-landsat` (Colección 1, nivel 1, escenas
T1), convierte a reflectancia en el techo de la atmósfera con los coeficientes del
MTL, quita nubes con la banda BQA y guarda un NDVI mediano por mes en la misma
rejilla para toda la serie. El formato de salida (`ndvi_AAAA-MM.nc`) es el mismo
que `historico.py`, así que `agave.py` puede usarlo directamente.

Uso:
    python -m agricultura.landsat --zona tequila --desde 1993-01 --hasta 2021-12 \
        --salida agricultura/resultados/tequila/historico_landsat/mensual
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
import rioxarray  # noqa: F401  (activa el accesor .rio)
import xarray as xr
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.transform import from_origin

from . import datos
from .config import ZONAS

BUCKET = "gcp-public-data-landsat"
API = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
ARCHIVOS = f"https://storage.googleapis.com/{BUCKET}"
SENSORES = ["LT05", "LE07", "LC08"]
# Bandas roja e infrarroja cercana por sensor
BANDAS = {"LT05": ("B3", "B4"), "LE07": ("B3", "B4"), "LC08": ("B4", "B5")}
# Path/row WRS-2 que cubren las zonas piloto de Jalisco
PATH_ROW = {"tequila": ["029/046", "030/046"], "los_altos": ["029/046"]}
NUBES_MAX = 70


def _json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def _texto(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode()


def listar_escenas(path_rows):
    """Carpetas de escenas T1 (L1TP) por sensor y path/row: {fecha: [carpeta, ...]}."""
    escenas = {}
    for sensor in SENSORES:
        for pr in path_rows:
            token = None
            while True:
                q = {"prefix": f"{sensor}/01/{pr}/", "delimiter": "/", "fields": "prefixes,nextPageToken"}
                if token:
                    q["pageToken"] = token
                r = _json(f"{API}?{urllib.parse.urlencode(q)}")
                for carpeta in r.get("prefixes", []):
                    m = re.search(r"_L1TP_\d{6}_(\d{8})_\d{8}_01_T1/$", carpeta)
                    if m:
                        escenas.setdefault(m.group(1), []).append(carpeta)
                token = r.get("nextPageToken")
                if not token:
                    break
    return escenas


def _mtl(carpeta):
    nombre = carpeta.rstrip("/").split("/")[-1]
    texto = _texto(f"{ARCHIVOS}/{carpeta}{nombre}_MTL.txt")
    valores = dict(re.findall(r"^\s*(\w+)\s*=\s*\"?([^\"\n]+)\"?\s*$", texto, flags=re.M))
    return nombre, valores


def _leer(url, rejilla, remuestreo=Resampling.nearest):
    with rasterio.open(url) as src, WarpedVRT(
        src, crs=rejilla["crs"], transform=rejilla["transform"], width=rejilla["ancho"],
        height=rejilla["alto"], resampling=remuestreo, nodata=0,
    ) as vrt:
        return vrt.read(1)


def _mascara_nubes(bqa, sensor):
    """True donde el pixel es útil (sin relleno, nube ni sombra de nube de confianza alta)."""
    relleno = (bqa & 1) > 0
    nube = (bqa >> 4) & 1
    sombra = (bqa >> 7) & 3
    malo = relleno | (nube == 1) | (sombra == 3)
    if sensor == "LC08":
        malo |= ((bqa >> 11) & 3) == 3  # cirros
    return ~malo & (bqa > 0)


def ndvi_escena(carpeta, rejilla):
    """NDVI de reflectancia TOA de una escena en la rejilla dada, o None si está muy nublada."""
    sensor = carpeta.split("/")[0]
    nombre, mtl = _mtl(carpeta)
    if float(mtl.get("CLOUD_COVER_LAND", mtl.get("CLOUD_COVER", 100))) > NUBES_MAX:
        return None
    sol = np.sin(np.radians(float(mtl["SUN_ELEVATION"])))
    ref = []
    for banda in BANDAS[sensor]:
        n = banda[1:]
        dn = _leer(f"{ARCHIVOS}/{carpeta}{nombre}_{banda}.TIF", rejilla, Resampling.bilinear).astype("float32")
        m = float(mtl[f"REFLECTANCE_MULT_BAND_{n}"])
        a = float(mtl[f"REFLECTANCE_ADD_BAND_{n}"])
        ref.append(np.where(dn > 0, (m * dn + a) / sol, np.nan))
    bqa = _leer(f"{ARCHIVOS}/{carpeta}{nombre}_BQA.TIF", rejilla).astype("uint16")
    rojo, nir = ref
    with np.errstate(all="ignore"):
        ndvi = (nir - rojo) / (nir + rojo)
    return np.where(_mascara_nubes(bqa, sensor), ndvi, np.nan).astype("float32")


def rejilla_zona(bbox, resolucion=30):
    """Rejilla UTM fija de la zona (misma para todas las escenas)."""
    from pyproj import Transformer

    epsg = datos.epsg_utm(bbox)
    tr = Transformer.from_crs(4326, epsg, always_xy=True)
    x0, y0 = tr.transform(bbox[0], bbox[1])
    x1, y1 = tr.transform(bbox[2], bbox[3])
    x0, y1 = np.floor(x0 / resolucion) * resolucion, np.ceil(y1 / resolucion) * resolucion
    ancho = int(np.ceil((x1 - x0) / resolucion))
    alto = int(np.ceil((y1 - y0) / resolucion))
    return {"crs": f"EPSG:{epsg}", "transform": from_origin(x0, y1, resolucion, resolucion),
            "ancho": ancho, "alto": alto, "x0": x0, "y1": y1, "res": resolucion}


def descargar(bbox, path_rows, desde, hasta, carpeta, simultaneos=8, meses=None, comprimido=False):
    """NDVI mensual. `meses`: lista de meses a bajar (p. ej. secas y lluvias); por omisión todos.
    `comprimido`: guarda cada mes como .npz con NDVI x10000 en int16 (para zonas grandes)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    rejilla = rejilla_zona(bbox)
    r = rejilla["res"]
    x = rejilla["x0"] + r / 2 + r * np.arange(rejilla["ancho"])
    y = rejilla["y1"] - r / 2 - r * np.arange(rejilla["alto"])
    print("Listando escenas Landsat...", flush=True)
    escenas = listar_escenas(path_rows)
    por_mes = {}
    for fecha, carpetas in escenas.items():
        clave = (int(fecha[:4]), int(fecha[4:6]))
        if desde <= clave <= hasta and (meses is None or clave[1] in meses):
            por_mes.setdefault(clave, []).extend(carpetas)
    print(f"  {sum(len(v) for v in por_mes.values())} escenas en {len(por_mes)} meses", flush=True)

    def seguro(carpeta_escena):
        try:
            return ndvi_escena(carpeta_escena, rejilla)
        except Exception as e:  # escenas con archivos faltantes o dañados
            print(f"  aviso: {carpeta_escena}: {e}", flush=True)
            return None

    with ThreadPoolExecutor(simultaneos) as pool:
        for (anio, mes), carpetas in sorted(por_mes.items()):
            ruta = carpeta / f"ndvi_{anio}-{mes:02d}.{'npz' if comprimido else 'nc'}"
            if ruta.exists():
                continue
            capas = [c for c in pool.map(seguro, carpetas) if c is not None]
            if not capas:
                continue
            with np.errstate(all="ignore"):
                mediana = np.nanmedian(np.stack(capas), 0)
            del capas
            if comprimido:
                entero = np.where(np.isfinite(mediana), np.round(mediana * 10000), -32768).astype("int16")
                np.savez_compressed(ruta, ndvi=entero, x=x, y=y, crs=rejilla["crs"])
                print(f"  {anio}-{mes:02d}: listo", flush=True)
                continue
            da = xr.DataArray(mediana[None], dims=("tiempo", "y", "x"),
                              coords={"tiempo": [np.datetime64(f"{anio}-{mes:02d}-15")], "y": y, "x": x},
                              name="ndvi").rio.write_crs(rejilla["crs"])
            da.to_netcdf(ruta)
            print(f"  {anio}-{mes:02d}: {len(capas)} escenas", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zona", choices=sorted(ZONAS))
    p.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    p.add_argument("--path-row", nargs="+", help="p. ej. 029/046 030/046 (obligatorio con --bbox)")
    p.add_argument("--meses", type=int, nargs="+", help="solo estos meses (p. ej. 3 4 5 7 8 9 10)")
    p.add_argument("--comprimido", action="store_true", help="guardar .npz int16 (zonas grandes)")
    p.add_argument("--desde", default="1993-01")
    p.add_argument("--hasta", default="2021-12")
    p.add_argument("--salida", type=Path, required=True)
    args = p.parse_args(argv)
    desde = tuple(int(v) for v in args.desde.split("-"))
    hasta = tuple(int(v) for v in args.hasta.split("-"))
    if args.bbox:
        bbox, path_rows = tuple(args.bbox), args.path_row
    else:
        bbox, path_rows = ZONAS[args.zona]["bbox"], PATH_ROW[args.zona]
    descargar(bbox, path_rows, desde, hasta, args.salida, meses=args.meses, comprimido=args.comprimido)


if __name__ == "__main__":
    main()
