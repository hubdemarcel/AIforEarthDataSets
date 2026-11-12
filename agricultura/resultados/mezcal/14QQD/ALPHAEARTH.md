# Mezcal 14QQD: reglas contra AlphaEarth, comparados con el SIAP 2025

Generado por `mezcal_alphaearth.py`. Sin etiquetas humanas: AlphaEarth aprende de las reglas (agave 2018–2023 contra las demás clases), limpiado con validación cruzada, y se juzga contra la superficie sembrada del SIAP 2025 por municipio, que es independiente.

## Limpieza de los ejemplos de entrenamiento

| clase de las reglas | ejemplos | AlphaEarth confirma |
|---|---|---|
| agave 2018–2023 | 4000.0 | 39 % |
| agua | 4000.0 | 100 % |
| bosque | 4000.0 | 97 % |
| cultivo anual | 4000.0 | 94 % |
| pastizal / matorral | 4000.0 | 91 % |
| selva baja | 4000.0 | 98 % |
| urbano | 4000.0 | 100 % |

Cohorte 2024 de las reglas: 20,648 ha, AlphaEarth confirma 5 %.

## Totales en los 115 municipios cubiertos al 95 % o más

| mapa | hectáreas | veces el SIAP | correlación con el SIAP (Spearman) | municipios a ±50 % del SIAP* |
|---|---|---|---|---|
| reglas | 26,365 | 4.5 | 0.57 | 4 de 27 |
| alphaearth | 14,663 | 2.5 | 0.49 | 10 de 27 |
| reglas_y_alphaearth | 4,354 | 0.7 | 0.59 | 9 de 27 |
| reglas_sin_2024 | 12,071 | 2.1 | 0.57 | 12 de 27 |
| SIAP sembrada 2025 | 5,865 | 1.0 | | |

*Municipios con 50 ha o más sembradas según el SIAP.

## Principales municipios mezcaleros

| municipio | SIAP | reglas | AlphaEarth | reglas + AlphaEarth |
|---|---|---|---|---|
| Miahuatlán de Porfirio Díaz | 1,265 | 3,774 | 1,041 | 461 |
| Santiago Matatlán | 796 | 562 | 501 | 200 |
| Tlacolula de Matamoros | 666 | 352 | 569 | 140 |
| San Juan del Río | 500 | 248 | 322 | 194 |
| San Luis Amatlán | 468 | 790 | 423 | 182 |
| San Carlos Yautepec | 460 | 245 | 154 | 106 |
| San Dionisio Ocotepec | 393 | 868 | 606 | 275 |
| Santa María Zoquitlán | 330 | 847 | 1,312 | 441 |
| Sitio de Xitlapehua | 292 | 71 | 64 | 22 |
| Heroica Ciudad de Ejutla de Crespo | 279 | 2,862 | 1,404 | 638 |
| San Vicente Coatlán | 222 | 466 | 58 | 19 |
| San Lorenzo Albarradas | 204 | 437 | 476 | 231 |
| San Pedro Totolápam | 202 | 587 | 661 | 246 |
| Villa Sola de Vega | 176 | 1,339 | 1,015 | 239 |
| La Compañía | 162 | 720 | 257 | 104 |

Tabla completa en `comparacion_alphaearth_siap.csv`. El SIAP cuenta agave sembrado y reportado; algo de exceso sobre el SIAP puede ser agave real no reportado o silvestre.
