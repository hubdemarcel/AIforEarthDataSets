"""Corrida desatendida: procesa los siguientes mosaicos pendientes de la cola.

Pensado para una sesión programada (p. ej. cada noche). Toma los primeros
mosaicos de `cola_mosaicos.txt` que todavía no tienen resultados, los procesa con
`mosaico.py`, borra el caché de imágenes para liberar disco y actualiza el resumen
por municipio. Subir los resultados (git commit/push) lo hace quien lo ejecuta.

Cuando la cola de Sentinel-2 se vacía, sigue con `cola_landsat.txt`: baja Landsat
2009–2017 de cada mosaico (meses de secas y lluvias), corre `historia_mosaico.py` para
fechar las plantaciones anteriores a 2018 y borra el caché de Landsat.

Uso:
    python -m agricultura.nocturno --max 2
"""

import argparse
import shutil
import time
from pathlib import Path

import pandas as pd

from . import historia_mosaico, landsat, mosaico, municipios

RAIZ = Path(__file__).parent
COLA = RAIZ / "cola_mosaicos.txt"
MOSAICOS = RAIZ / "resultados" / "mosaicos"
COLA_LANDSAT = RAIZ / "cola_landsat.txt"
PATH_ROW = RAIZ / "landsat_path_row.csv"  # path/row WRS-2 que tocan el cuadro propio de cada mosaico
LANDSAT_DESDE, LANDSAT_HASTA = (2009, 1), (2017, 12)
DISCO_MIN_GB = 6  # caché mensual (~3 GB) + métricas (~0.6 GB) + margen


def pendientes():
    ids = [l.strip() for l in COLA.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [i for i in ids if not (MOSAICOS / i / "uso_suelo.tif").exists()]


def pendientes_landsat():
    ids = [l.strip() for l in COLA_LANDSAT.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [i for i in ids if (MOSAICOS / i / "uso_suelo.tif").exists()
            and not (MOSAICOS / i / "plantacion_historica_total.csv").exists()]


def historia_landsat(mid):
    """Landsat 2009–2017 del mosaico + historia de plantación; borra el caché al terminar."""
    import rasterio
    from rasterio.warp import transform_bounds

    carpeta = MOSAICOS / mid
    with rasterio.open(carpeta / "uso_suelo.tif") as src:
        epsg = src.crs.to_epsg()
        bbox = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    path_rows = pd.read_csv(PATH_ROW).set_index("mosaico").loc[mid, "path_row"].split()
    landsat.descargar(bbox, path_rows, LANDSAT_DESDE, LANDSAT_HASTA, carpeta / "landsat_mensual",
                      meses=mosaico.MESES, comprimido=True, epsg=epsg)
    historia_mosaico.main(["--mosaico", str(carpeta)])
    shutil.rmtree(carpeta / "landsat_mensual", ignore_errors=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max", type=int, default=2, help="mosaicos por corrida")
    p.add_argument("--desde", type=int, default=2018)
    p.add_argument("--hasta", type=int, default=2026)
    args = p.parse_args(argv)

    cola = pendientes()
    print(f"Pendientes en la cola: {len(cola)}. Esta corrida: {cola[:args.max]}", flush=True)
    hechos = []
    for mid in cola[:args.max]:
        libre = shutil.disk_usage(MOSAICOS).free / 1e9
        if libre < DISCO_MIN_GB:
            print(f"Alto: quedan {libre:.1f} GB libres (mínimo {DISCO_MIN_GB}). Libera disco antes de seguir.", flush=True)
            break
        inicio = time.time()
        salida = MOSAICOS / mid
        mosaico.main(["--mosaico", mid, "--desde", str(args.desde), "--hasta", str(args.hasta),
                      "--simultaneos", "1", "--salida", str(salida)])
        shutil.rmtree(salida / "mensual", ignore_errors=True)
        hechos.append((mid, (time.time() - inicio) / 60))

    if not cola:
        for mid in pendientes_landsat()[:args.max]:
            libre = shutil.disk_usage(MOSAICOS).free / 1e9
            if libre < DISCO_MIN_GB:
                print(f"Alto: quedan {libre:.1f} GB libres (mínimo {DISCO_MIN_GB}).", flush=True)
                break
            inicio = time.time()
            print(f"Historia Landsat de {mid}...", flush=True)
            historia_landsat(mid)
            print(f"Mosaico {mid} (Landsat): {(time.time() - inicio) / 60:.0f} min", flush=True)
        print(f"Quedan {len(pendientes_landsat())} mosaicos en la cola de Landsat.", flush=True)

    if hechos:
        municipios.main(["--mosaicos", str(MOSAICOS), "--salida", str(RAIZ / "resultados" / "municipios")])
    for mid, minutos in hechos:
        print(f"Mosaico {mid}: {minutos:.0f} min", flush=True)
    print(f"Quedan {len(pendientes())} mosaicos en la cola.", flush=True)


if __name__ == "__main__":
    main()
