"""Mapa de agave probable de un mosaico de mezcal y su comparación con el SIAP por municipio.

Un pixel es agave probable si cumple las tres cosas que mostró `mezcal_anomalias.py`:

1. Las reglas lo ven como agave en pie plantado 2018–2023 (sin la cohorte 2024 sospechosa).
2. En AlphaEarth 2025 se parece más al agave del núcleo mezcalero (Matatlán, Tlacolula,
   San Juan del Río, San Luis Amatlán; mosaico 14QQD) que a selva baja, pastizal /
   matorral, cultivo anual o bosque (vecinos más cercanos, k = 15). El agave de referencia
   sale siempre de 14QQD; las demás clases, del propio mosaico.
3. El terreno cambió entre 2018 y 2025 (AlphaEarth) más que el percentil 75 de la selva
   baja y el matorral estables del mosaico: hubo desmonte y plantación.

Uso:
    python -m agricultura.mezcal_probable --mosaico agricultura/resultados/mezcal/14QQD
    python -m agricultura.mezcal_probable --mosaico agricultura/resultados/mezcal/14QRD \
        --referencia agricultura/resultados/mezcal/14QQD
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from sklearn.neighbors import KNeighborsClassifier

from .embeddings_puntos import SIN_DATO, descuantizar
from .exportar_agaves_pro import _norm
from .mezcal_anomalias import AGAVE, MUNICIPIOS, NUCLEO, POR_CLASE, REFERENCIA
from .municipios import _area_propia

RAIZ = Path(__file__).parent


def cargar(carpeta):
    import rioxarray
    uso = rioxarray.open_rasterio(carpeta / "uso_suelo.tif").squeeze("band", drop=True)
    est = rioxarray.open_rasterio(carpeta / "agave_establecimiento.tif").squeeze("band", drop=True).values
    mun = gpd.read_file(MUNICIPIOS).reset_index(drop=True)
    ids = rasterize(zip(mun.to_crs(uso.rio.crs).geometry, mun.index + 1), out_shape=uso.shape,
                    transform=uso.rio.transform(), fill=0, dtype="int32") - 1
    return uso, est, mun, ids


def emb(ruta):
    with rasterio.open(ruta) as src:
        return src.read().reshape(64, -1)


def agave_del_nucleo(carpeta, rng):
    """Embeddings 2025 de una muestra del agave 2018–2023 del núcleo mezcalero (en 14QQD)."""
    uso, est, mun, ids = cargar(carpeta)
    num = {v: k for k, v in enumerate(mun.municipio)}
    m = (uso.values == AGAVE) & (est >= 2018) & (est <= 2023) & _area_propia(uso) \
        & np.isin(ids, [num[x] for x in NUCLEO])
    e = emb(carpeta / "alphaearth_2025.tif")
    idx = np.flatnonzero(m.ravel() & (e[0] != SIN_DATO))
    idx = rng.choice(idx, min(POR_CLASE, len(idx)), replace=False)
    return descuantizar(e[:, idx].T)


def coseno(a, b):
    return 1 - (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mosaico", type=Path, required=True)
    p.add_argument("--referencia", type=Path, help="mosaico con el núcleo mezcalero (por omisión, el mismo)")
    args = p.parse_args(argv)
    rng = np.random.default_rng(0)
    ref = args.referencia or args.mosaico

    X_ref, y_ref = [agave_del_nucleo(ref, rng)], ["agave"] * POR_CLASE
    uso, est, mun, ids = cargar(args.mosaico)
    clase = uso.values.ravel()
    propio = _area_propia(uso).ravel()
    e25, e18 = emb(args.mosaico / "alphaearth_2025.tif"), emb(args.mosaico / "alphaearth_2018.tif")
    valido = (e25[0] != SIN_DATO) & (e18[0] != SIN_DATO) & propio
    for k, n in REFERENCIA.items():
        cand = np.flatnonzero((clase == k) & valido)
        s = rng.choice(cand, min(POR_CLASE, len(cand)), replace=False)
        X_ref.append(descuantizar(e25[:, s].T))
        y_ref += [n] * len(s)
    knn = KNeighborsClassifier(15, metric="cosine").fit(np.concatenate(X_ref), np.array(y_ref))

    estable = rng.choice(np.flatnonzero(np.isin(clase, [7, 8]) & valido), 20000, replace=False)
    umbral = np.quantile(coseno(descuantizar(e18[:, estable].T), descuantizar(e25[:, estable].T)), 0.75)

    est_r = est.ravel()
    candidatos = np.flatnonzero((clase == AGAVE) & (est_r >= 2018) & (est_r <= 2023) & valido)
    parecido = np.zeros(len(candidatos), bool)
    cambio = np.zeros(len(candidatos), bool)
    for i in range(0, len(candidatos), 50_000):
        b = candidatos[i:i + 50_000]
        a25, a18 = descuantizar(e25[:, b].T), descuantizar(e18[:, b].T)
        parecido[i:i + 50_000] = knn.predict(a25) == "agave"
        cambio[i:i + 50_000] = coseno(a18, a25) > umbral
    print(f"{len(candidatos) * 0.04:,.0f} ha de agave 2018–2023 de las reglas; se parecen al núcleo "
          f"{100 * parecido.mean():.0f} %, cambiaron {100 * cambio.mean():.0f} %, ambas "
          f"{100 * (parecido & cambio).mean():.0f} %", flush=True)

    # 0 nada, 1 reglas, 2 reglas + parecido, 3 reglas + parecido + cambio (agave probable)
    mapa = np.zeros(clase.shape, "uint8")
    mapa[(clase == AGAVE) & propio] = 1
    mapa[candidatos[parecido]] = 2
    mapa[candidatos[parecido & cambio]] = 3
    mapa = mapa.reshape(uso.shape)
    perfil = dict(driver="GTiff", width=uso.shape[1], height=uso.shape[0], count=1, dtype="uint8", nodata=0,
                  crs=uso.rio.crs, transform=uso.rio.transform(), compress="deflate")
    with rasterio.open(args.mosaico / "agave_probable.tif", "w", **perfil) as dst:
        dst.write(mapa, 1)

    ha = abs(np.prod(uso.rio.resolution())) / 10_000
    propio2 = propio.reshape(uso.shape) & (ids >= 0)
    t = mun[["municipio"]].copy()
    cub = np.bincount(ids[propio2], minlength=len(mun)) * ha
    t["cubierto_pct"] = (cub / (mun.to_crs(6372).area.values / 10_000) * 100).clip(max=100).round(0)
    capas = {"reglas_ha": (mapa >= 1),
             "reglas_sin_2024_ha": (mapa >= 1) & (est <= 2023),
             "parecido_nucleo_ha": mapa >= 2,
             "agave_probable_ha": mapa == 3}
    for n, m in capas.items():
        t[n] = np.bincount(ids[propio2 & m], minlength=len(mun)) * ha
    sp = pd.read_csv(RAIZ / "datos_externos" / "siap_agave_municipal.csv")
    sp = sp[(sp.Anio == 2025) & (sp.Nomestado == "Oaxaca") & (sp.Nomcultivo == "Agave")]
    t["siap_sembrada_2025_ha"] = t.municipio.map(_norm).map(sp.groupby(sp.Nommunicipio.map(_norm)).Sembrada.sum()) \
        .fillna(0).values
    t = t[t.cubierto_pct > 0].round(0)
    t = t[(t[list(capas)].sum(axis=1) > 0) | (t.siap_sembrada_2025_ha > 0)]
    t["probable_entre_siap"] = (t.agave_probable_ha / t.siap_sembrada_2025_ha.where(t.siap_sembrada_2025_ha > 0)) \
        .round(1)
    t = t.sort_values("agave_probable_ha", ascending=False)
    t.to_csv(args.mosaico / "agave_probable_por_municipio.csv", index=False)

    c = t[t.cubierto_pct >= 95]
    con = c[c.siap_sembrada_2025_ha >= 50]
    nombre = args.mosaico.name
    lineas = [f"# Agave probable en {nombre} contra el SIAP 2025\n",
              "Generado por `mezcal_probable.py`: agave de las reglas plantado 2018–2023 que además se parece "
              "al agave del núcleo mezcalero en AlphaEarth y cuyo terreno cambió entre 2018 y 2025. "
              "Sin etiquetas humanas.\n",
              f"## Totales en los {len(c)} municipios cubiertos al 95 % o más\n",
              "| mapa | hectáreas | veces el SIAP | correlación con el SIAP (Spearman) | municipios a ±50 % del SIAP* |",
              "|---|---|---|---|---|"]
    for n in capas:
        tot = c[n].sum()
        cerca = (con[n] / con.siap_sembrada_2025_ha).between(0.5, 1.5).sum()
        lineas.append(f"| {n.removesuffix('_ha').replace('_', ' ')} | {tot:,.0f} | "
                      f"{tot / max(c.siap_sembrada_2025_ha.sum(), 1):.1f} | "
                      f"{c[n].corr(c.siap_sembrada_2025_ha, method='spearman'):.2f} | {cerca} de {len(con)} |")
    lineas += [f"| SIAP sembrada 2025 | {c.siap_sembrada_2025_ha.sum():,.0f} | 1.0 | | |",
               "\n*Municipios con 50 ha o más sembradas según el SIAP.\n",
               "## Municipios con más agave probable\n",
               "| municipio | cubierto | SIAP | reglas | agave probable | probable / SIAP |",
               "|---|---|---|---|---|---|"]
    for _, r in t.head(20).iterrows():
        lineas.append(f"| {r.municipio} | {r.cubierto_pct:.0f} % | {r.siap_sembrada_2025_ha:,.0f} | "
                      f"{r.reglas_ha:,.0f} | {r.agave_probable_ha:,.0f} | "
                      f"{'' if pd.isna(r.probable_entre_siap) else r.probable_entre_siap} |")
    lineas.append("\nTabla completa en `agave_probable_por_municipio.csv`; mapa en `agave_probable.tif` "
                  "(1 reglas, 2 + parecido al núcleo, 3 agave probable).")
    (args.mosaico / "AGAVE_PROBABLE.md").write_text("\n".join(lineas) + "\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
