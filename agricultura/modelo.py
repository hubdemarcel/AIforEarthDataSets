"""Entrenamiento, validación y aplicación del clasificador de cultivos (Random Forest)."""

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict

from .config import NOMBRE_CLASE


def _nuevo_bosque(n_arboles, semilla):
    # RandomForest de scikit-learn acepta NaN (pixeles sin dato) directamente.
    return RandomForestClassifier(
        n_estimators=n_arboles,
        class_weight="balanced_subsample",
        min_samples_leaf=2,
        n_jobs=-1,
        random_state=semilla,
    )


def entrenar(X, y, grupos, nombres_caracteristicas, n_arboles=300, semilla=0):
    """Entrena el modelo y lo valida con predios que no vio (validación cruzada por predio).

    Devuelve (paquete, reporte). `paquete` se guarda con `guardar` y se usa en `predecir`.
    """
    predios_por_clase = pd.Series(grupos).groupby(y).nunique()
    pliegues = int(min(5, predios_por_clase.min()))
    nombres = [NOMBRE_CLASE[c] for c in np.unique(y)]

    lineas = [
        f"Pixeles de entrenamiento: {len(y)}  |  predios: {len(np.unique(grupos))}",
        "Predios por clase:",
        *[f"  {NOMBRE_CLASE[c]:<22}{n}" for c, n in predios_por_clase.items()],
        "",
    ]
    if pliegues >= 2:
        cv = StratifiedGroupKFold(n_splits=pliegues, shuffle=True, random_state=semilla)
        pred = cross_val_predict(_nuevo_bosque(n_arboles, semilla), X, y, groups=grupos, cv=cv)
        matriz = pd.DataFrame(confusion_matrix(y, pred), index=nombres, columns=nombres)
        lineas += [
            f"Validación cruzada por predio ({pliegues} pliegues):",
            classification_report(y, pred, target_names=nombres, digits=3, zero_division=0),
            "Matriz de confusión (filas = real, columnas = predicho):",
            matriz.to_string(),
        ]
    else:
        lineas.append("Sin validación: hace falta al menos 2 predios de cada clase.")

    bosque = _nuevo_bosque(n_arboles, semilla).fit(X, y)
    importancia = pd.Series(bosque.feature_importances_, index=nombres_caracteristicas)
    lineas += ["", "Características más importantes:", importancia.nlargest(15).round(4).to_string()]

    paquete = {"modelo": bosque, "caracteristicas": list(nombres_caracteristicas)}
    return paquete, "\n".join(lineas)


def guardar(paquete, ruta):
    joblib.dump(paquete, ruta)


def cargar(ruta):
    return joblib.load(ruta)


def predecir(paquete, pila, filas_por_bloque=200_000):
    """Clasifica cada pixel. Devuelve (clase, probabilidad) como DataArrays (y, x)."""
    esperadas = paquete["caracteristicas"]
    if list(pila.caracteristica.values) != esperadas:
        pila = pila.sel(caracteristica=esperadas)
    n_car, alto, ancho = pila.shape
    X = pila.values.reshape(n_car, -1).T
    clase = np.zeros(len(X), dtype="uint8")
    prob = np.zeros(len(X), dtype="float32")
    modelo = paquete["modelo"]
    for inicio in range(0, len(X), filas_por_bloque):
        bloque = X[inicio : inicio + filas_por_bloque]
        p = modelo.predict_proba(bloque)
        clase[inicio : inicio + len(bloque)] = modelo.classes_[p.argmax(1)]
        prob[inicio : inicio + len(bloque)] = p.max(1)
    sin_dato = np.isnan(X).all(1)
    clase[sin_dato] = 0
    prob[sin_dato] = np.nan

    plantilla = pila.isel(caracteristica=0, drop=True)
    return (
        plantilla.copy(data=clase.reshape(alto, ancho)).rename("clase"),
        plantilla.copy(data=prob.reshape(alto, ancho)).rename("probabilidad"),
    )


def superficie(clase):
    """Hectáreas por clase en el mapa."""
    res_x, res_y = clase.rio.resolution()
    ha_por_pixel = abs(res_x * res_y) / 10_000
    codigos, conteo = np.unique(clase.values[clase.values > 0], return_counts=True)
    tabla = pd.DataFrame(
        {"clase": [NOMBRE_CLASE[c] for c in codigos], "hectareas": (conteo * ha_por_pixel).round(1)}
    )
    tabla["porcentaje"] = (100 * tabla.hectareas / tabla.hectareas.sum()).round(1)
    return tabla.sort_values("hectareas", ascending=False, ignore_index=True)




def agrupar(pila, n_grupos=12, muestra=300_000, semilla=0):
    """Agrupa pixeles con calendario de verdor parecido (sin etiquetas).

    Usa los valores mensuales de los índices; cada grupo es un "patrón" de uso del
    suelo que después se puede identificar (agave, maíz, bosque...).
    Devuelve (grupo DataArray (y, x) con 0 = sin dato, centros DataFrame).
    """
    mensuales = [c for c in pila.caracteristica.values if "_m" in c]
    datos = pila.sel(caracteristica=mensuales)
    n_car, alto, ancho = datos.shape
    X = datos.values.reshape(n_car, -1).T
    validos = np.flatnonzero(~np.isnan(X).any(1))
    rng = np.random.default_rng(semilla)
    entrenamiento = X[rng.choice(validos, min(muestra, len(validos)), replace=False)]
    media, desv = entrenamiento.mean(0), entrenamiento.std(0) + 1e-6
    kmeans = MiniBatchKMeans(n_grupos, random_state=semilla, n_init=5, batch_size=10_000)
    kmeans.fit((entrenamiento - media) / desv)

    grupo = np.zeros(len(X), dtype="uint8")
    grupo[validos] = kmeans.predict((X[validos] - media) / desv) + 1
    centros = pd.DataFrame(kmeans.cluster_centers_ * desv + media, columns=mensuales)
    centros.index = np.arange(1, n_grupos + 1)
    centros.index.name = "grupo"
    plantilla = pila.isel(caracteristica=0, drop=True)
    return plantilla.copy(data=grupo.reshape(alto, ancho)).rename("grupo"), centros
