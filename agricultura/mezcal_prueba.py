"""Fase 1 del plan del mezcal: compara un mosaico de Oaxaca contra el SIAP por municipio.

Usa las reglas del tequila tal cual (`mosaico.py`), sin ajustar. Solo dice qué tan lejos
estamos; no es un resultado para publicar (`PLAN-MEZCAL.md`).

Uso:
    python -m agricultura.mezcal_prueba --mosaico agricultura/resultados/mezcal/14QQD
"""

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .agave import CLASES
from .exportar_agaves_pro import _norm
from .municipios import AGAVE, resumir_mosaico

RAIZ = Path(__file__).parent
MUNICIPIOS = RAIZ / "datos_externos" / "municipios_oaxaca.geojson"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", type=Path, required=True)
    args = p.parse_args(argv)
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    por_clase, agave, _, cubierto = resumir_mosaico(args.mosaico, mun)

    s = pd.read_csv(RAIZ / "datos_externos" / "siap_agave_municipal.csv")
    s = s[(s.Anio == 2025) & (s.Nomestado == "Oaxaca") & (s.Nomcultivo == "Agave")]
    siap = s.groupby(s.Nommunicipio.map(_norm))[["Sembrada", "Cosechada"]].sum()

    clases = por_clase.unstack("clase", fill_value=0).rename(columns=CLASES)
    t = mun[["municipio"]].copy()
    t["cubierto_pct"] = (cubierto / (mun.to_crs(6372).area / 10_000) * 100).clip(upper=100).round(0)
    t["agave_ha"] = clases.get(CLASES[AGAVE], pd.Series(dtype=float)).reindex(t.index, fill_value=0)
    t["agave_desde_2018_ha"] = agave[agave.index.get_level_values("est") >= 2018] \
        .groupby("mun").sum().reindex(t.index, fill_value=0)
    clave = t.municipio.map(_norm)
    t["siap_sembrada_2025_ha"] = clave.map(siap.Sembrada).fillna(0).values
    t["siap_cosechada_2025_ha"] = clave.map(siap.Cosechada).fillna(0).values
    t = t[(t.cubierto_pct > 0) & ((t.agave_ha > 0) | (t.siap_sembrada_2025_ha > 0))].round(0)
    t = t.sort_values("siap_sembrada_2025_ha", ascending=False)
    t.to_csv(args.mosaico / "comparacion_siap_por_municipio.csv", index=False)
    completos = t[t.cubierto_pct >= 95]
    print(f"Municipios cubiertos al 95 %+: {len(completos)}")
    print(completos[["agave_ha", "siap_sembrada_2025_ha"]].sum().round(0).to_string())
    print(t.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
