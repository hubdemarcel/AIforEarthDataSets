"""Paquete de datos de agave en pie para integrar en agaves.pro.

Junta los resultados por mosaico en tablas y un GeoJSON por municipio, listos para una
página web, en `agricultura/para_agaves_pro/`. No calcula nada nuevo: solo reúne lo que
ya dejaron `historia_mosaico.py`, `municipios.py` y el SIAP.

Uso:
    python -m agricultura.exportar_agaves_pro
"""

import json
import shutil
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

RAIZ = Path(__file__).parent
MOSAICOS = RAIZ / "resultados" / "mosaicos"
SALIDA = RAIZ / "para_agaves_pro"
SIN_CALIBRAR = {"Tamaulipas"}


def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return t.replace(" de ocampo", "").strip()


def main():
    SALIDA.mkdir(exist_ok=True)
    cohortes = pd.concat(pd.read_csv(f) for f in sorted(MOSAICOS.glob("*/agave_viejo_por_municipio.csv")))
    cohortes = (cohortes.groupby(["estado", "municipio", "denominacion_origen", "plantacion", "jima"])
                .hectareas.sum().round(1).reset_index())
    cohortes.to_csv(SALIDA / "agave_viejo_cohortes.csv", index=False)

    viejo = cohortes[cohortes.jima == 0].groupby(["estado", "municipio"]).hectareas.sum()
    joven = pd.read_csv(RAIZ / "resultados" / "municipios" / "agave_por_municipio_y_anio.csv") \
        .set_index(["estado", "municipio"]).agave_en_pie_ha
    s = pd.read_csv(RAIZ / "datos_externos" / "siap_agave_municipal.csv")
    s = s[(s.Anio == 2025) & (s.Nomcultivo == "Agave")]
    siap = s.groupby([s.Nomestado.map(_norm), s.Nommunicipio.map(_norm)]).Sembrada.sum()

    mun = gpd.read_file(RAIZ / "datos_externos" / "municipios_estados_do.geojson")
    clave = list(zip(mun.estado, mun.municipio))
    mun["viejo_en_pie_ha"] = [round(float(viejo.get(k, 0))) for k in clave]
    mun["joven_en_pie_ha"] = [round(float(joven.get(k, 0))) for k in clave]
    mun["siap_sembrada_2025_ha"] = [round(float(siap.get((_norm(e), _norm(m)), 0))) for e, m in clave]
    mun["calibrado"] = ~mun.estado.isin(SIN_CALIBRAR)
    tabla = mun.drop(columns="geometry")
    tabla.to_csv(SALIDA / "agave_en_pie_municipios.csv", index=False)
    geo = mun.copy()
    geo["geometry"] = geo.geometry.simplify(0.003, preserve_topology=True)
    geo.to_file(SALIDA / "agave_en_pie_municipios.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)

    cal = cohortes[~cohortes.estado.isin(SIN_CALIBRAR)]
    resumen = {
        "nota": "Hectáreas satelitales sin calibrar contra el SIAP; usar para tendencias y comparación entre municipios. "
                "Tamaulipas queda fuera de los totales.",
        "mosaicos": len(list(MOSAICOS.glob("*/agave_viejo_por_municipio.csv"))),
        "jimas_por_anio_ha": {int(a): round(float(h)) for a, h in
                              cal[cal.jima > 0].groupby("jima").hectareas.sum().loc[2018:].items()},
        "en_pie_2026_por_plantacion_ha": {int(a): round(float(h)) for a, h in
                                          cal[cal.jima == 0].groupby("plantacion").hectareas.sum().items()},
        "por_estado": {e: {"viejo_en_pie_ha": int(g.viejo_en_pie_ha.sum()), "joven_en_pie_ha": int(g.joven_en_pie_ha.sum()),
                           "siap_sembrada_2025_ha": int(g.siap_sembrada_2025_ha.sum()), "calibrado": e not in SIN_CALIBRAR}
                       for e, g in tabla.groupby("estado")},
    }
    (SALIDA / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    for nombre in ("oferta_agave_viejo_total.csv", "oferta_agave_viejo_por_municipio.csv",
                   "oferta_agave_maduro_total.csv", "oferta_agave_maduro_por_municipio.csv"):
        shutil.copy(RAIZ / "resultados" / "municipios" / nombre, SALIDA / nombre)
    shutil.copy(RAIZ / "reportes" / "demo_agave_en_pie.html", SALIDA / "demo_agave_en_pie.html")
    print(json.dumps(resumen["por_estado"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
