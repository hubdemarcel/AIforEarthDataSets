# AlphaEarth en los puntos de verificación (prueba sin etiquetas humanas)

Embeddings anuales de AlphaEarth (Google DeepMind, CC-BY 4.0), 64 dimensiones a 10 m, mediana de 3 × 3 pixeles. Generado por `analisis_embeddings.py`.

**Esto mide coherencia, no precisión**: las clases son las de las reglas o de la geografía. La precisión real sale cuando se marquen los puntos en las páginas de verificación.

## 1. Coherencia de las clases de las reglas (mezcal 14QQD, AlphaEarth 2025)

Porcentaje de puntos cuyos 5 vecinos más parecidos tienen mayoría de su misma clase:

| clase de las reglas | puntos | acuerdo con vecinos |
|---|---|---|
| agave_2018_2023 | 59 | 75 % |
| cultivo_anual | 25 | 72 % |
| matorral_pastizal | 30 | 70 % |
| agave_2024 | 35 | 57 % |
| selva_baja | 25 | 52 % |
| bosque | 10 | 50 % |
| agave_cosechado | 15 | 40 % |

Matriz completa en `alphaearth/mezcal_coherencia.csv`.

## 2. ¿A qué se parece la cohorte 2024 sospechosa?

Los 35 puntos que las reglas llaman agave plantado en 2024, clasificados por sus vecinos entre las demás clases:

| se parecen a | puntos | % |
|---|---|---|
| agave_2018_2023 | 16 | 46 % |
| selva_baja | 13 | 37 % |
| matorral_pastizal | 3 | 9 % |
| cultivo_anual | 3 | 9 % |

## 3. Fechado independiente: año de mayor cambio del embedding

Mediana del mayor cambio de un año a otro (distancia coseno; más alto = cambió más el terreno):

| clase | cambio mediano |
|---|---|
| agave_cosechado | 0.140 |
| agave_2024 | 0.092 |
| agave_2018_2023 | 0.090 |
| selva_baja | 0.086 |
| cultivo_anual | 0.082 |
| matorral_pastizal | 0.079 |
| bosque | 0.026 |

Agave 2018–2023 (59 puntos): el año de mayor cambio cae a ±1 año del establecimiento de las reglas en 42 % de los puntos (exacto 14 %).

## 4. Agave seguro contra imitadores (Jalisco y Michoacán, AlphaEarth 2025)

Regresión logística, dejando uno fuera, umbral 0.5:

| grupo | puntos | marcados agave por AlphaEarth | filtro NDMI abril > 0.03 (README) |
|---|---|---|---|
| agave_seguro | 32 | 91 % | 97 % conserva |
| aguacate | 29 | 14 % | 46 % conserva |
| sierra | 7 | 14 % | 43 % conserva |

Ojo: los grupos salen de la geografía (Jalisco contra Michoacán), así que parte de la separación puede ser región y no cultivo. Hay que confirmarlo con los puntos marcados a mano.

## 5. Los 150 puntos de tequila: AlphaEarth contra el modelo espectral actual

Correlación (Spearman) entre la probabilidad de AlphaEarth y la del modelo espectral (`p`): 0.67

| zona | puntos | p media (espectral) | prob. media AlphaEarth |
|---|---|---|---|
| Guanajuato Bajío | 19 | 0.51 | 0.47 |
| Guanajuato norte | 20 | 0.37 | 0.34 |
| Jalisco en verificación | 20 | 0.55 | 0.40 |
| Michoacán DO | 16 | 0.50 | 0.46 |
| Michoacán aguacate | 14 | 0.33 | 0.29 |
| Núcleo Jalisco | 16 | 0.60 | 0.39 |
| Sierra y Nayarit | 14 | 0.48 | 0.37 |
| Tamaulipas | 20 | 0.23 | 0.25 |
| Tierra Caliente | 10 | 0.30 | 0.37 |

