"""¿Ayudan los embeddings de AlphaEarth? Pruebas en los puntos de verificación sin etiquetas humanas.

Mientras no estén marcados a mano los puntos, las "etiquetas" son lo que dicen las reglas
(`clase_modelo`) o la geografía (imitadores). Las pruebas miden coherencia, no precisión:

1. Coherencia por clase (mezcal): vecinos más cercanos (k = 5, coseno) dejando uno fuera.
   Si los puntos que las reglas llaman agave caen junto a otros "agave", la clase es
   consistente; si caen junto a matorral, las reglas mezclan cosas distintas.
2. Cohorte 2024 sospechosa: se entrena con las demás clases y se ve a qué se parece.
3. Fechado independiente: año de mayor cambio del embedding contra el año de
   establecimiento de las reglas.
4. Agave seguro contra imitadores (aguacate, sierra): regresión logística dejando uno fuera,
   comparada con el filtro NDMI de abril > 0.03 de `imitadores/README.md`.

Uso:
    python -m agricultura.analisis_embeddings
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

from .embeddings_puntos import DIMS

V = Path(__file__).parent / "resultados" / "verificacion"
SALIDA = V / "alphaearth"


def cargar(carpeta, puntos):
    e = pd.read_csv(V / carpeta / "alphaearth.csv.gz")
    p = pd.read_csv(V / carpeta / puntos)
    return e, p


def anio(e, a):
    return e[e.anio == a].set_index("id")[DIMS]


def unit(X):
    X = np.asarray(X, float)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def coherencia(X, y, k=5):
    knn = KNeighborsClassifier(k, metric="cosine")
    pred = cross_val_predict(knn, X, y, cv=LeaveOneOut())
    t = pd.crosstab(pd.Series(y, name="reglas"), pd.Series(pred, name="vecinos_alphaearth"))
    return t, (pred == y)


def cambio_maximo(e, pid):
    s = e[e.id == pid].sort_values("anio")
    if len(s) < 3:
        return np.nan, np.nan
    X = unit(s[DIMS].values)
    d = 1 - (X[1:] * X[:-1]).sum(1)  # distancia coseno entre años seguidos
    k = int(np.argmax(d))
    return int(s.anio.values[k + 1]), float(d[k])


def mezcal(lineas):
    e, p = cargar("mezcal_200", "puntos_mezcal.csv")
    X = anio(e, 2025)
    p = p[p.id.isin(X.index)].set_index("id")
    X = X.loc[p.index]

    lineas.append("## 1. Coherencia de las clases de las reglas (mezcal 14QQD, AlphaEarth 2025)\n")
    t, ok = coherencia(X.values, p.clase_modelo.to_numpy(dtype=object))
    t.to_csv(SALIDA / "mezcal_coherencia.csv")
    acuerdo = pd.Series(ok, index=p.index).groupby(p.clase_modelo).mean().mul(100).round(0)
    lineas.append("Porcentaje de puntos cuyos 5 vecinos más parecidos tienen mayoría de su misma clase:\n")
    lineas.append("| clase de las reglas | puntos | acuerdo con vecinos |\n|---|---|---|")
    for c, v in acuerdo.sort_values(ascending=False).items():
        lineas.append(f"| {c} | {(p.clase_modelo == c).sum()} | {v:.0f} % |")
    lineas.append(f"\nMatriz completa en `alphaearth/mezcal_coherencia.csv`.\n")

    lineas.append("## 2. ¿A qué se parece la cohorte 2024 sospechosa?\n")
    entren = p.clase_modelo.ne("agave_2024")
    knn = KNeighborsClassifier(5, metric="cosine").fit(X[entren].values, p.clase_modelo[entren].to_numpy(dtype=object))
    pred = pd.Series(knn.predict(X[~entren].values)).value_counts()
    n = (~entren).sum()
    lineas.append(f"Los {n} puntos que las reglas llaman agave plantado en 2024, clasificados por sus vecinos "
                  "entre las demás clases:\n")
    lineas.append("| se parecen a | puntos | % |\n|---|---|---|")
    for c, v in pred.items():
        lineas.append(f"| {c} | {v} | {100 * v / n:.0f} % |")
    lineas.append("")

    lineas.append("## 3. Fechado independiente: año de mayor cambio del embedding\n")
    filas = []
    for pid, r in p.iterrows():
        a, d = cambio_maximo(e, pid)
        filas.append({"id": pid, "clase_modelo": r.clase_modelo, "establecimiento": r.establecimiento,
                      "anio_cambio": a, "cambio": d})
    f = pd.DataFrame(filas)
    f.to_csv(SALIDA / "mezcal_fechado.csv", index=False)
    lineas.append("Mediana del mayor cambio de un año a otro (distancia coseno; más alto = cambió más el terreno):\n")
    lineas.append("| clase | cambio mediano |\n|---|---|")
    for c, v in f.groupby("clase_modelo").cambio.median().sort_values(ascending=False).items():
        lineas.append(f"| {c} | {v:.3f} |")
    ag = f[f.clase_modelo.eq("agave_2018_2023") & f.establecimiento.notna()]
    if len(ag):
        dif = (ag.anio_cambio - ag.establecimiento).abs()
        # el embedding del año de plantación ya incluye el desmonte; se acepta ±1 año
        lineas.append(f"\nAgave 2018–2023 ({len(ag)} puntos): el año de mayor cambio cae a ±1 año del "
                      f"establecimiento de las reglas en {100 * (dif <= 1).mean():.0f} % de los puntos "
                      f"(exacto {100 * (dif == 0).mean():.0f} %).\n")
    return e, p


def imitadores(lineas):
    e, p = cargar("imitadores", "puntos.csv")
    X = anio(e, 2025)
    p = p[p.id.isin(X.index)].set_index("id")
    X = X.loc[p.index]
    y = p.grupo.eq("agave_seguro").values
    lineas.append("## 4. Agave seguro contra imitadores (Jalisco y Michoacán, AlphaEarth 2025)\n")
    lr = LogisticRegression(C=1.0, max_iter=2000)
    prob = cross_val_predict(lr, X.values, y, cv=LeaveOneOut(), method="predict_proba")[:, 1]
    p["prob_agave_ae"] = prob.round(3)
    lineas.append("Regresión logística, dejando uno fuera, umbral 0.5:\n")
    lineas.append("| grupo | puntos | marcados agave por AlphaEarth | filtro NDMI abril > 0.03 (README) |\n|---|---|---|---|")
    ndmi = {"agave_seguro": "97 % conserva", "aguacate": "46 % conserva", "sierra": "43 % conserva"}
    for g in ["agave_seguro", "aguacate", "sierra"]:
        m = p.grupo.eq(g)
        lineas.append(f"| {g} | {m.sum()} | {100 * (prob[m.values] >= 0.5).mean():.0f} % | {ndmi[g]} |")
    lineas.append("\nOjo: los grupos salen de la geografía (Jalisco contra Michoacán), así que parte de la "
                  "separación puede ser región y no cultivo. Hay que confirmarlo con los puntos marcados a mano.\n")
    p[["grupo", "prob_agave_ae"]].to_csv(SALIDA / "imitadores_prob.csv")
    return lr.fit(X.values, y), X, p


def tequila_150(lineas, modelo):
    e, p = cargar("puntos_150", "puntos_verificacion.csv")
    X = anio(e, 2025)
    p = p[p.id.isin(X.index)].set_index("id")
    p["prob_agave_ae"] = modelo.predict_proba(X.loc[p.index].values)[:, 1].round(3)
    p.to_csv(SALIDA / "puntos_150_prob.csv")
    lineas.append("## 5. Los 150 puntos de tequila: AlphaEarth contra el modelo espectral actual\n")
    lineas.append(f"Correlación (Spearman) entre la probabilidad de AlphaEarth y la del modelo espectral (`p`): "
                  f"{p.prob_agave_ae.corr(p.p, method='spearman'):.2f}\n")
    lineas.append("| zona | puntos | p media (espectral) | prob. media AlphaEarth |\n|---|---|---|---|")
    for z, g in p.groupby("zona"):
        lineas.append(f"| {z} | {len(g)} | {g.p.mean():.2f} | {g.prob_agave_ae.mean():.2f} |")
    lineas.append("")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    lineas = ["# AlphaEarth en los puntos de verificación (prueba sin etiquetas humanas)\n",
              "Embeddings anuales de AlphaEarth (Google DeepMind, CC-BY 4.0), 64 dimensiones a 10 m, "
              "mediana de 3 × 3 pixeles. Generado por `analisis_embeddings.py`.\n",
              "**Esto mide coherencia, no precisión**: las clases son las de las reglas o de la geografía. "
              "La precisión real sale cuando se marquen los puntos en las páginas de verificación.\n"]
    mezcal(lineas)
    modelo, _, _ = imitadores(lineas)
    tequila_150(lineas, modelo)
    (SALIDA / "README.md").write_text("\n".join(lineas) + "\n")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
