# 200 puntos de verificación de agave mezcalero (14QQD, Oaxaca)

Puntos para marcar a mano en la página "Verificar agave mezcalero" (artifact de claude.ai),
igual que `puntos_150/` para el tequila. Las respuestas quedan en la colección
`respuestas` de la página (`valor` = si / no / nose, `detalle` si es agave, `motivo` si no).

Muestreo estratificado sobre `resultados/mezcal/14QQD/uso_suelo.tif`, solo pixeles en el
centro de un bloque de 3 × 3 de la misma clase y en el cuadro propio del mosaico; ~70 %
en municipios con 50 ha o más sembradas según el SIAP 2025:

| `clase_modelo` | Puntos |
|---|---|
| agave plantado 2018–2023 | 60 |
| agave "plantado" 2024 (sospechoso) | 35 |
| matorral / pastizal | 30 |
| selva baja | 25 |
| cultivo anual | 25 |
| agave cosechado | 15 |
| bosque | 10 |

La página no muestra la clase del modelo ni el año de plantación, para no sesgar.
`serie_puntos.json` es la historia de verdor 2018–2026 que sí se muestra.
