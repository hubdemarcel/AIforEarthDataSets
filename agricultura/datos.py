"""Descarga de Sentinel-2 L2A y elevación (Copernicus DEM) desde AWS Open Data.

Se leen directamente los archivos COG públicos de los buckets `sentinel-cogs`
(catálogo de Earth Search) y `copernicus-dem-30m`. Solo se lee el recorte de la
zona y cada mes se reduce a un compuesto mediano sin nubes.
"""

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import xarray as xr

S2_BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
S2_PREFIJO = "sentinel-s2-l2a-cogs"
DEM_BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"

# Nombre de asset en el catálogo -> banda Sentinel-2
ASSETS_S2 = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "rededge1": "B05",
    "rededge2": "B06",
    "rededge3": "B07",
    "nir": "B08",
    "nir08": "B8A",
    "swir16": "B11",
    "swir22": "B12",
}
BANDAS_S2 = list(ASSETS_S2.values())
# Clases de la capa SCL que se consideran cielo despejado:
# 4 vegetación, 5 suelo desnudo, 6 agua, 7 sin clasificar.
SCL_VALIDOS = [4, 5, 6, 7]


def epsg_utm(bbox):
    """Código EPSG de la zona UTM que contiene el centro del bbox."""
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    zona = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zona


def mosaicos_mgrs(bbox, paso=0.02):
    """Mosaicos MGRS de Sentinel-2 (p. ej. '13QFD') que cubren el bbox."""
    import mgrs

    conv = mgrs.MGRS()
    lons = np.append(np.arange(bbox[0], bbox[2], paso), bbox[2])
    lats = np.append(np.arange(bbox[1], bbox[3], paso), bbox[3])
    return sorted({conv.toMGRS(lat, lon, MGRSPrecision=0) for lat in lats for lon in lons})


def _leer_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _listar(prefijo):
    """Subcarpetas de un prefijo del bucket S3 (listado público)."""
    url = f"{S2_BUCKET}/?list-type=2&delimiter=/&prefix={prefijo}"
    return re.findall(r"<Prefix>([^<]+/)</Prefix>", _leer_url(url).decode())[1:]


def escenas_s2(bbox, anio, mes, nubes_max=70):
    """Escenas (pystac.Item) de Sentinel-2 L2A del mes que cubren el bbox."""
    import pystac

    carpetas = []
    for mosaico in mosaicos_mgrs(bbox):
        zona, banda_lat, cuadro = mosaico[:-3], mosaico[-3], mosaico[-2:]
        carpetas += _listar(f"{S2_PREFIJO}/{zona}/{banda_lat}/{cuadro}/{anio}/{mes}/")

    def item(carpeta):
        nombre = carpeta.rstrip("/").split("/")[-1]
        return pystac.Item.from_dict(json.loads(_leer_url(f"{S2_BUCKET}/{carpeta}{nombre}.json")))

    with ThreadPoolExecutor(8) as pool:
        items = list(pool.map(item, carpetas))
    # Algunas fechas tienen varias versiones (_0, _1, _2) y no todas apuntan a los COG
    # públicos; se conserva la versión más reciente con archivos públicos por mosaico y fecha.
    por_escena = {}
    for i in sorted(items, key=lambda i: i.id):
        if i.assets["red"].href.startswith(S2_BUCKET):
            por_escena[i.id.rsplit("_", 2)[0]] = i
    return [i for i in por_escena.values() if i.properties.get("eo:cloud_cover", 100) < nubes_max]


def _offset(item):
    """Valor a restar a los niveles digitales para obtener reflectancia ×10000.

    Desde la versión de procesamiento 04.00 los datos traen +1000; Earth Search
    lo indica con `earthsearch:boa_offset_applied` cuando ya lo quitó.
    """
    if item.properties.get("earthsearch:boa_offset_applied"):
        return 0
    return 1000 if item.properties.get("s2:processing_baseline", "00.00") >= "04.00" else 0


def ultimos_12_meses(hasta=None):
    """Los 12 meses completos que terminan en `hasta` (anio, mes); por omisión el último mes cerrado."""
    if hasta is None:
        hoy = date.today()
        hasta = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    anio, mes = hasta
    periodos = []
    for _ in range(12):
        periodos.append((anio, mes))
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    return periodos[::-1]


def compuesto_mensual_s2(bbox, periodos, resolucion=10, nubes_max=70):
    """Reflectancia (0–1) mediana mensual de Sentinel-2 L2A sin nubes.

    `periodos`: 12 meses consecutivos [(anio, mes), ...], p. ej. de `ultimos_12_meses()`.
    Devuelve un Dataset con una variable por banda y dimensiones (mes, y, x), donde
    `mes` es el mes del calendario (1–12) y la coordenada `anio` dice de qué año es.
    """
    import odc.stac

    odc.stac.configure_rio(cloud_defaults=True)
    geobox = None
    compuestos = {}
    for anio, mes in periodos:
        items = escenas_s2(bbox, anio, mes, nubes_max)
        if not items:
            print(f"  S2 {anio}-{mes:02d}: sin escenas útiles")
            continue
        opciones = {"geobox": geobox} if geobox is not None else {
            "bbox": bbox, "crs": f"EPSG:{epsg_utm(bbox)}", "resolution": resolucion
        }
        ds = odc.stac.load(
            items,
            bands=list(ASSETS_S2) + ["scl"],
            groupby="solar_day",
            chunks={"x": 1024, "y": 1024},
            **opciones,
        )
        geobox = ds.odc.geobox
        # La misma fecha en varios mosaicos comparte procesamiento, así que basta un offset por día.
        offset_dia = {np.datetime64(i.datetime.replace(tzinfo=None), "D"): _offset(i) for i in items}
        offset = xr.DataArray(
            [offset_dia.get(np.datetime64(t, "D"), 0) for t in ds.time.values], dims="time"
        )
        valido = ds.scl.isin(SCL_VALIDOS)
        bandas = ds[list(ASSETS_S2)].rename(ASSETS_S2).astype("float32")
        refl = ((bandas - offset) / 10000).where(valido & (bandas > 0))
        compuestos[(anio, mes)] = refl.median("time").astype("float32").compute()
        print(f"  S2 {anio}-{mes:02d}: {len(ds.time)} fechas")

    if not compuestos:
        raise RuntimeError(f"No hay escenas de Sentinel-2 para {bbox} en {periodos[0]}–{periodos[-1]}")
    plantilla = next(iter(compuestos.values()))
    meses = []
    for anio, mes in sorted(periodos, key=lambda p: p[1]):
        ds = compuestos.get((anio, mes))
        if ds is None:
            ds = xr.full_like(plantilla, np.nan)
        meses.append(ds.expand_dims(mes=[mes]).assign_coords(anio=("mes", [anio])))
    return xr.concat(meses, dim="mes")


def _url_dem(lat, lon):
    ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
    ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
    nombre = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"
    return f"{DEM_BUCKET}/{nombre}/{nombre}.tif"


def elevacion(bbox, plantilla):
    """Elevación (m) y pendiente (grados) del Copernicus DEM 30 m en la rejilla de `plantilla`."""
    import rioxarray
    from rasterio.enums import Resampling
    from rioxarray.merge import merge_arrays

    mosaicos = [
        rioxarray.open_rasterio(_url_dem(lat, lon)).squeeze("band", drop=True)
        for lat in range(int(np.floor(bbox[1])), int(np.floor(bbox[3])) + 1)
        for lon in range(int(np.floor(bbox[0])), int(np.floor(bbox[2])) + 1)
    ]
    dem = merge_arrays(mosaicos) if len(mosaicos) > 1 else mosaicos[0]
    elev = dem.rio.reproject_match(plantilla, resampling=Resampling.bilinear).astype("float32")
    elev = elev.assign_coords(x=plantilla.x, y=plantilla.y)
    return xr.Dataset({"elevacion": elev, "pendiente": pendiente(elev)})


def pendiente(elev):
    """Pendiente en grados a partir de una elevación con coordenadas x/y en metros."""
    res_x = abs(float(elev.x[1] - elev.x[0]))
    res_y = abs(float(elev.y[1] - elev.y[0]))
    dz_dy, dz_dx = np.gradient(elev.values, res_y, res_x)
    grados = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype("float32")
    return elev.copy(data=grados)
