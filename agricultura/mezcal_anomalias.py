"""¿Es agave real el exceso sobre el SIAP? Tres pruebas sin etiquetas humanas, por municipio.

En Ejutla, Sola de Vega, Miahuatlán y Zoquitlán las reglas ven mucho más agave que el
SIAP. Puede ser error (matorral o selva que se parece al agave) o agave sembrado y no
reportado. Se compara el agave de las reglas (plantado 2018–2023) de esos municipios con
el del núcleo mezcalero (Matatlán, Tlacolula, San Juan del Río, San Luis Amatlán), donde
las reglas y el SIAP casi coinciden:

1. Parecido (AlphaEarth 2025): vecinos más cercanos (k = 15) entre pixeles de referencia
   tomados fuera de los municipios en duda: agave del núcleo, selva baja, pastizal /
   matorral, cultivo anual y bosque. Base de comparación: el agave del núcleo
   (dejando fuera los pixeles de referencia).
2. Forma de parcela: manchas conectadas de agave; un predio sembrado es compacto
   (0.5 ha o más), el matorral confundido sale en pixeles sueltos.
3. Cambio del terreno 2018 → 2025 (AlphaEarth): una plantación nueva cambia el pixel
   (desmonte y plantación); el matorral que siempre estuvo ahí, no. Umbral: percentil 75
   del cambio de la selva baja y el matorral estables.

Uso:
    python -m agricultura.mezcal_anomalias --mosaico agricultura/resultados/mezcal/14QQD
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from sklearn.neighbors import KNeighborsClassifier

from .embeddings_puntos import SIN_DATO, descuantizar
from .municipios import _area_propia

RAIZ = Path(__file__).parent
MUNICIPIOS = RAIZ / "datos_externos" / "municipios_oaxaca.geojson"
NUCLEO = ["Santiago Matatlán", "Tlacolula de Matamoros", "San Juan del Río", "San Luis Amatlán"]
EN_DUDA = ["Heroica Ciudad de Ejutla de Crespo", "Villa Sola de Vega", "Miahuatlán de Porfirio Díaz",
           "Santa María Zoquitlán"]
REFERENCIA = {6: "cultivo anual", 7: "selva baja", 8: "pastizal / matorral", 3: "bosque"}
AGAVE = 4
POR_CLASE = 3000
MIN_PARCELA = 13  # pixeles de 20 m ≈ 0.5 ha


def emb(ruta):
    with rasterio.open(ruta) as src:
        return src.read().reshape(64, -1)


def main(argv=None):
    import rioxarray
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", type=Path, required=True)
    args = p.parse_args(argv)
    rng = np.random.default_rng(0)

    uso = rioxarray.open_rasterio(args.mosaico / "uso_suelo.tif").squeeze("band", drop=True)
    est = rioxarray.open_rasterio(args.mosaico / "agave_establecimiento.tif").squeeze("band", drop=True).values
    clase = uso.values
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=clase.shape,
                    transform=uso.rio.transform(), fill=0, dtype="int32") - 1
    propio = _area_propia(uso)
    nombre = dict(enumerate(mun.municipio))
    num = {v: k for k, v in nombre.items()}
    nucleo_ids = [num[m] for m in NUCLEO]
    duda_ids = [num[m] for m in EN_DUDA]
    agave = (clase == AGAVE) & (est >= 2018) & (est <= 2023) & propio
    e25 = emb(args.mosaico / "alphaearth_2025.tif")
    valido = (e25[0] != SIN_DATO) & propio.ravel()

    # 1. Parecido con vecinos de referencia (fuera de los municipios en duda)
    fuera = ~np.isin(ids, duda_ids).ravel() & valido
    ref_idx, ref_y = [], []
    nucleo_agave = np.flatnonzero(agave.ravel() & np.isin(ids, nucleo_ids).ravel() & valido)
    sel = rng.choice(nucleo_agave, min(POR_CLASE, len(nucleo_agave)), replace=False)
    ref_idx.append(sel)
    ref_y += ["agave del núcleo"] * len(sel)
    for k, n in REFERENCIA.items():
        cand = np.flatnonzero((clase.ravel() == k) & fuera)
        s = rng.choice(cand, min(POR_CLASE, len(cand)), replace=False)
        ref_idx.append(s)
        ref_y += [n] * len(s)
    ref_idx = np.concatenate(ref_idx)
    knn = KNeighborsClassifier(15, metric="cosine").fit(descuantizar(e25[:, ref_idx].T), np.array(ref_y))
    usados = np.zeros(e25.shape[1], bool)
    usados[ref_idx] = True

    # 3. Cambio 2018 → 2025
    ruta18 = args.mosaico / "alphaearth_2018.tif"
    cambio = None
    if ruta18.exists():
        e18 = emb(ruta18)

        def dist(idx):
            a, b = descuantizar(e18[:, idx].T), descuantizar(e25[:, idx].T)
            return 1 - (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))

        estable = np.flatnonzero(np.isin(clase.ravel(), [7, 8]) & fuera & (e18[0] != SIN_DATO))
        umbral = np.quantile(dist(rng.choice(estable, 20000, replace=False)), 0.75)
        cambio = (dist, umbral)

    # 2. Manchas conectadas (8 vecinos)
    etiquetas, _ = ndimage.label(agave, structure=np.ones((3, 3)))
    tam = np.bincount(etiquetas.ravel())
    tam_pixel = tam[etiquetas]

    filas = []
    for grupo, lista in [("núcleo", NUCLEO), ("en duda", EN_DUDA)]:
        for m in lista:
            en = agave & (ids == num[m])
            idx = np.flatnonzero(en.ravel() & valido & ~usados)
            if not len(idx):
                continue
            pred = pd.Series(knn.predict(descuantizar(e25[:, idx].T))).value_counts(normalize=True)
            fila = {"grupo": grupo, "municipio": m, "agave_reglas_ha": round(en.sum() * 0.04),
                    "parecido_agave_nucleo_pct": round(100 * pred.get("agave del núcleo", 0)),
                    "parecido_selva_pct": round(100 * pred.get("selva baja", 0)),
                    "parecido_matorral_pct": round(100 * pred.get("pastizal / matorral", 0)),
                    "parecido_cultivo_pct": round(100 * pred.get("cultivo anual", 0)),
                    "en_parcelas_05ha_pct": round(100 * (tam_pixel[en] >= MIN_PARCELA).mean()),
                    "mancha_mediana_ha": round(float(np.median(tam_pixel[en])) * 0.04, 2)}
            if cambio:
                dist, umbral = cambio
                d = dist(idx)
                fila["cambio_2018_2025_pct"] = round(100 * (d > umbral).mean())
            filas.append(fila)
    t = pd.DataFrame(filas)
    # Agave probable: el de las reglas que se parece al del núcleo
    t["agave_probable_ha"] = (t.agave_reglas_ha * t.parecido_agave_nucleo_pct / 100).round()
    sp = pd.read_csv(RAIZ / "datos_externos" / "siap_agave_municipal.csv")
    sp = sp[(sp.Anio == 2025) & (sp.Nomestado == "Oaxaca") & (sp.Nomcultivo == "Agave")]
    from .exportar_agaves_pro import _norm
    siap = sp.groupby(sp.Nommunicipio.map(_norm)).Sembrada.sum()
    t["siap_sembrada_2025_ha"] = t.municipio.map(_norm).map(siap).fillna(0)
    t.to_csv(args.mosaico / "anomalias_pruebas.csv", index=False)

    cols = ["municipio", "siap_sembrada_2025_ha", "agave_reglas_ha", "agave_probable_ha",
            "parecido_agave_nucleo_pct", "parecido_selva_pct", "parecido_matorral_pct", "parecido_cultivo_pct",
            "en_parcelas_05ha_pct", "mancha_mediana_ha"] + (["cambio_2018_2025_pct"] if cambio else [])
    lineas = ["# ¿Es agave real el exceso sobre el SIAP? (14QQD)\n",
              "Generado por `mezcal_anomalias.py`. Agave de las reglas plantado 2018–2023, por municipio. "
              "Ver el método en el código.\n",
              "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        lineas.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    if cambio:
        lineas.append(f"\nUmbral de cambio 2018→2025 (percentil 75 de selva baja y matorral estables): "
                      f"{cambio[1]:.3f} de distancia coseno.")
    (args.mosaico / "ANOMALIAS.md").write_text("\n".join(lineas) + "\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
