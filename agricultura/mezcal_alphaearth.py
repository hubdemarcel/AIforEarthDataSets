"""Mezcal fase 2 sin etiquetas humanas: AlphaEarth contra las reglas, comparado con el SIAP por municipio.

No hay puntos marcados a mano, así que el clasificador aprende de las propias reglas y se
juzga con un dato independiente, el SIAP:

1. Ejemplos de entrenamiento (muestra estratificada de `uso_suelo.tif`):
   agave = agave en pie plantado 2018–2023; no agave = bosque, cultivo anual, selva baja,
   otro (pastizal/matorral), urbano y agua. Se dejan fuera la cohorte 2024 sospechosa y el
   agave cosechado.
2. Limpieza: regresión logística con validación cruzada (5 partes); se tiran los ejemplos
   cuya probabilidad fuera de la parte contradice su etiqueta (< 0.5). Así se quita el
   ruido de las reglas sin que nadie marque nada. Se reentrena con lo que queda.
3. Mapa de probabilidad de agave para todo el mosaico (`agave_alphaearth.tif`, 0–100).
4. Hectáreas por municipio de tres mapas contra la superficie sembrada del SIAP 2025:
   reglas, AlphaEarth, y reglas filtradas por AlphaEarth (agave en ambos).

Uso:
    python -m agricultura.mezcal_alphaearth --mosaico agricultura/resultados/mezcal/14QQD
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict

from .embeddings_puntos import SIN_DATO, descuantizar
from .exportar_agaves_pro import _norm
from .municipios import _area_propia

RAIZ = Path(__file__).parent
MUNICIPIOS = RAIZ / "datos_externos" / "municipios_oaxaca.geojson"
AGAVE, COSECHADO = 4, 5
NO_AGAVE = {1: "agua", 2: "urbano", 3: "bosque", 6: "cultivo anual", 7: "selva baja", 8: "pastizal / matorral"}
POR_CLASE = 4000
UMBRAL = 0.5


def leer(carpeta):
    import rioxarray
    uso = rioxarray.open_rasterio(carpeta / "uso_suelo.tif").squeeze("band", drop=True)
    est = rioxarray.open_rasterio(carpeta / "agave_establecimiento.tif").squeeze("band", drop=True).values
    with rasterio.open(carpeta / "alphaearth_2025.tif") as src:
        assert src.shape == uso.shape, "AlphaEarth y uso_suelo deben estar en la misma rejilla"
        emb = src.read()  # (64, alto, ancho) int8
    return uso, est, emb


def muestra(clase, est, valido, rng):
    """Índices planos y etiqueta (1 agave, 0 no) de la muestra estratificada de entrenamiento."""
    grupos = {"agave 2018–2023": (clase == AGAVE) & (est >= 2018) & (est <= 2023)}
    grupos.update({n: clase == k for k, n in NO_AGAVE.items()})
    idx, y, g = [], [], []
    for nombre, m in grupos.items():
        cand = np.flatnonzero(m.ravel() & valido)
        if not len(cand):
            continue
        sel = rng.choice(cand, min(POR_CLASE, len(cand)), replace=False)
        idx.append(sel)
        y.append(np.full(len(sel), nombre.startswith("agave")))
        g.append(np.full(len(sel), nombre))
    return np.concatenate(idx), np.concatenate(y).astype(int), np.concatenate(g)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", type=Path, required=True)
    args = p.parse_args(argv)
    rng = np.random.default_rng(0)

    uso, est, emb = leer(args.mosaico)
    clase = uso.values
    alto, ancho = clase.shape
    plano = emb.reshape(64, -1)
    valido = (plano[0] != SIN_DATO) & (clase.ravel() > 0)

    idx, y, grupo = muestra(clase, est, valido, rng)
    X = descuantizar(plano[:, idx].T)
    lr = LogisticRegression(C=1.0, max_iter=3000)
    prob_cv = cross_val_predict(lr, X, y, cv=5, method="predict_proba")[:, 1]
    acuerdo = np.where(y == 1, prob_cv >= UMBRAL, prob_cv < UMBRAL)
    limpieza = pd.DataFrame({"grupo": grupo, "acuerdo": acuerdo}).groupby("grupo").acuerdo.agg(["size", "mean"])
    limpieza.columns = ["ejemplos", "se_quedan"]
    print("Ejemplos que AlphaEarth confirma (validación cruzada):\n", limpieza.round(2).to_string(), flush=True)
    modelo = LogisticRegression(C=1.0, max_iter=3000).fit(X[acuerdo], y[acuerdo])

    prob = np.full(alto * ancho, 255, "uint8")
    for i in range(0, alto * ancho, 2_000_000):
        b = slice(i, i + 2_000_000)
        v = valido[b]
        if v.any():
            prob[b][v] = np.round(modelo.predict_proba(descuantizar(plano[:, b][:, v].T))[:, 1] * 100)
    prob = prob.reshape(alto, ancho)
    perfil = dict(driver="GTiff", width=ancho, height=alto, count=1, dtype="uint8", nodata=255,
                  crs=uso.rio.crs, transform=uso.rio.transform(), compress="deflate")
    with rasterio.open(args.mosaico / "agave_alphaearth.tif", "w", **perfil) as dst:
        dst.write(prob, 1)

    ae = (prob >= UMBRAL * 100) & (prob != 255)
    reglas = clase == AGAVE
    mapas = {"reglas_ha": reglas, "alphaearth_ha": ae, "reglas_y_alphaearth_ha": reglas & ae,
             "reglas_sin_2024_ha": reglas & (est <= 2023)}

    # Cohorte 2024 de las reglas: qué parte confirma AlphaEarth
    c24 = reglas & (est >= 2024) & (prob != 255)
    print(f"Cohorte 2024 de las reglas: {c24.sum() * 0.04:,.0f} ha; AlphaEarth confirma "
          f"{100 * ae[c24].mean():.0f} %", flush=True)

    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=clase.shape,
                    transform=uso.rio.transform(), fill=0, dtype="int32")
    propio = _area_propia(uso) & (ids > 0)
    ha = abs(np.prod(uso.rio.resolution())) / 10_000
    t = mun[["municipio"]].copy()
    cubierto = np.bincount(ids[propio] - 1, minlength=len(mun)) * ha
    t["cubierto_pct"] = (cubierto / (mun.to_crs(6372).area.values / 10_000) * 100).clip(max=100).round(0)
    for nombre, m in mapas.items():
        t[nombre] = np.bincount(ids[propio & m] - 1, minlength=len(mun)) * ha
    s = pd.read_csv(RAIZ / "datos_externos" / "siap_agave_municipal.csv")
    s = s[(s.Anio == 2025) & (s.Nomestado == "Oaxaca") & (s.Nomcultivo == "Agave")]
    siap = s.groupby(s.Nommunicipio.map(_norm)).Sembrada.sum()
    t["siap_sembrada_2025_ha"] = t.municipio.map(_norm).map(siap).fillna(0).values
    t = t[t.cubierto_pct > 0].round(0)
    t = t[(t[list(mapas)].sum(axis=1) > 0) | (t.siap_sembrada_2025_ha > 0)]
    t = t.sort_values("siap_sembrada_2025_ha", ascending=False)
    t.to_csv(args.mosaico / "comparacion_alphaearth_siap.csv", index=False)

    c = t[t.cubierto_pct >= 95]
    lineas = ["# Mezcal 14QQD: reglas contra AlphaEarth, comparados con el SIAP 2025\n",
              "Generado por `mezcal_alphaearth.py`. Sin etiquetas humanas: AlphaEarth aprende de las reglas "
              "(agave 2018–2023 contra las demás clases), limpiado con validación cruzada, y se juzga contra la "
              "superficie sembrada del SIAP 2025 por municipio, que es independiente.\n",
              "## Limpieza de los ejemplos de entrenamiento\n",
              "| clase de las reglas | ejemplos | AlphaEarth confirma |\n|---|---|---|"]
    for g, r in limpieza.iterrows():
        lineas.append(f"| {g} | {r.ejemplos} | {100 * r.se_quedan:.0f} % |")
    lineas += [f"\nCohorte 2024 de las reglas: {c24.sum() * ha:,.0f} ha, AlphaEarth confirma "
               f"{100 * ae[c24].mean():.0f} %.\n",
               f"## Totales en los {len(c)} municipios cubiertos al 95 % o más\n",
               "| mapa | hectáreas | veces el SIAP | correlación con el SIAP (Spearman) | municipios a ±50 % del SIAP* |",
               "|---|---|---|---|---|"]
    con_siap = c[c.siap_sembrada_2025_ha >= 50]
    for nombre in list(mapas):
        tot = c[nombre].sum()
        cerca = ((con_siap[nombre] / con_siap.siap_sembrada_2025_ha).between(0.5, 1.5)).sum()
        lineas.append(f"| {nombre.removesuffix('_ha')} | {tot:,.0f} | {tot / c.siap_sembrada_2025_ha.sum():.1f} | "
                      f"{c[nombre].corr(c.siap_sembrada_2025_ha, method='spearman'):.2f} | "
                      f"{cerca} de {len(con_siap)} |")
    lineas += [f"| SIAP sembrada 2025 | {c.siap_sembrada_2025_ha.sum():,.0f} | 1.0 | | |",
               "\n*Municipios con 50 ha o más sembradas según el SIAP.\n",
               "## Principales municipios mezcaleros\n",
               "| municipio | SIAP | reglas | AlphaEarth | reglas + AlphaEarth |\n|---|---|---|---|---|"]
    for _, r in t.head(15).iterrows():
        lineas.append(f"| {r.municipio} | {r.siap_sembrada_2025_ha:,.0f} | {r.reglas_ha:,.0f} | "
                      f"{r.alphaearth_ha:,.0f} | {r.reglas_y_alphaearth_ha:,.0f} |")
    lineas.append("\nTabla completa en `comparacion_alphaearth_siap.csv`. El SIAP cuenta agave sembrado y "
                  "reportado; algo de exceso sobre el SIAP puede ser agave real no reportado o silvestre.")
    (args.mosaico / "ALPHAEARTH.md").write_text("\n".join(lineas) + "\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
