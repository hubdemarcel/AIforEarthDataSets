"""Serie anual para el modelo de precio del agave: precio real, demanda y oferta.

- Precio: precio medio rural nacional del SIAP (valor ÷ producción, cultivo Agave),
  en pesos de 2025 por kilo (deflactado con el INPC de Banxico).
- Demanda: agave consumido por la industria del tequila (CRT), miles de toneladas.
- Oferta: superficie sembrada nacional de agave (SIAP, hectáreas en pie) y su
  rezago: lo plantado hace 5–8 años es lo que hoy está en edad de jima.
"""

from pathlib import Path

import pandas as pd

EXT = Path(__file__).resolve().parent.parent / "datos_externos"


def serie_anual():
    siap = pd.read_csv(EXT / "siap_agave_resumen.csv")
    siap = siap[siap.cultivo == "Agave"].groupby("anio")[["sembrada_ha", "cosechada_ha", "produccion", "valor_pesos"]].sum()
    inpc = pd.read_csv(EXT / "inpc_anual.csv").set_index("anio")["factor_a_pesos_2025"]
    crt = pd.read_csv(EXT / "crt_tequila_anual.csv").set_index("anio")
    crt = crt[crt.anio_parcial.isna()]

    df = pd.DataFrame(index=range(1983, 2026))
    df.index.name = "anio"
    df["precio_corriente_kg"] = siap.valor_pesos / siap.produccion / 1000
    df["precio_real_kg"] = df.precio_corriente_kg * inpc
    df["sembrada_ha"] = siap.sembrada_ha
    df["cosechada_ha"] = siap.cosechada_ha
    df["produccion_t"] = siap.produccion
    df["demanda_agave_kt"] = crt.agave_total_kt
    df["export_ml"] = crt.export_total_ml
    return df
