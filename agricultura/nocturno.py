"""Corrida desatendida: procesa los siguientes mosaicos pendientes de la cola.

Pensado para una sesión programada (p. ej. cada noche). Toma los primeros
mosaicos de `cola_mosaicos.txt` que todavía no tienen resultados, los procesa con
`mosaico.py`, borra el caché de imágenes para liberar disco y actualiza el resumen
por municipio. Subir los resultados (git commit/push) lo hace quien lo ejecuta.

Uso:
    python -m agricultura.nocturno --max 2
"""

import argparse
import shutil
import time
from pathlib import Path

from . import mosaico, municipios

RAIZ = Path(__file__).parent
COLA = RAIZ / "cola_mosaicos.txt"
MOSAICOS = RAIZ / "resultados" / "mosaicos"


def pendientes():
    ids = [l.strip() for l in COLA.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return [i for i in ids if not (MOSAICOS / i / "uso_suelo.tif").exists()]


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
        inicio = time.time()
        salida = MOSAICOS / mid
        mosaico.main(["--mosaico", mid, "--desde", str(args.desde), "--hasta", str(args.hasta),
                      "--simultaneos", "1", "--salida", str(salida)])
        shutil.rmtree(salida / "mensual", ignore_errors=True)
        hechos.append((mid, (time.time() - inicio) / 60))

    if hechos:
        municipios.main(["--mosaicos", str(MOSAICOS), "--salida", str(RAIZ / "resultados" / "municipios")])
    for mid, minutos in hechos:
        print(f"Mosaico {mid}: {minutos:.0f} min", flush=True)
    print(f"Quedan {len(pendientes())} mosaicos en la cola.", flush=True)


if __name__ == "__main__":
    main()
