# Demanda de agave, producción y exportación de tequila (CRT) y mezcal (COMERCAM)

Copiado desde agaves.pro (PC 1) el 2026-10-10 para la herramienta de predicción. La demanda real del agave es lo que
consumen las tequileras (`agave_total_kt`): junto con la superficie y el precio del SIAP explica el ciclo de precios.

| Archivo | Qué trae |
|---|---|
| `crt_tequila_anual.csv` | Por año, 1995–2026: agave consumido (miles de t), producción y exportación de tequila (millones de litros a 40 % Alc. Vol.), separado tequila / tequila 100 % agave, exportación a granel y envasada, y consumo nacional aproximado (producción − exportación; no es dato del CRT). 2026 parcial |
| `crt_exportaciones_mensuales_por_pais.csv` | Exportaciones de tequila por mes y país destino, 1997-01 a 2026-09, 153 destinos, litros a 40 % Alc. Vol. |
| `crt_economia_tequila.json` | El archivo original del atlas de agaves.pro (tablero público Power BI del CRT, «EstadisticasCRTweb»), con exportación acumulada por país |
| `comercam_economia_mezcal.json` | Mezcal 2011–2024: producción, envasado nacional y de exportación (litros a 45 % Alc. Vol.), participación por estado 2024. COMERCAM, Informe Estadístico 2025 |

## Serie anual (CRT)

| Año | Agave consumido (miles de t) | Producción (M litros) | Exportación (M litros) | % 100 % agave en exportación | % a granel | Nacional aprox. (M litros) |
|---|---|---|---|---|---|---|
| 2005 | 689 | 210 | 117 | 18 % | 65 % | 93 |
| 2010 | 1,015 | 257 | 153 | 31 % | 55 % | 105 |
| 2015 | 789 | 228 | 183 | 43 % | 46 % | 46 |
| 2019 | 1,343 | 352 | 247 | 53 % | 37 % | 105 |
| 2020 | 1,407 | 374 | 287 | 57 % | 34 % | 87 |
| 2021 | 2,019 | 527 | 339 | 62 % | 29 % | 188 |
| 2022 | **2,611** | **651** | 419 | 64 % | 27 % | 232 |
| 2023 | 2,288 | 599 | 401 | 66 % | 25 % | 197 |
| 2024 | 1,891 | 496 | 402 | 68 % | 24 % | 94 |
| 2025 | 2,189 | 584 | 408 | 68 % | 24 % | 176 |

Lectura: la demanda de agave tocó máximo en 2022 (2.6 Mt) y bajó, mientras la superficie sembrada siguió subiendo hasta
307,131 ha en 2025 (SIAP). La exportación se estancó en ~400 M litros desde 2022. Destinos 2025: Estados Unidos 82 %
(331 M litros); España, Alemania, Canadá y Reino Unido 1–2 % cada uno.

## Cuidados
- Unidades del tablero del CRT: producción y exportación en millones de litros a 40 % Alc. Vol.; agave en miles de toneladas.
  Verificar contra el tablero antes de publicar cifras.
- 2026 en la serie anual es parcial (meses disponibles al descargar el tablero); en el archivo mensual llega a septiembre.
- No sumar estas exportaciones con las de SIAVI o Data México (miden el mismo flujo con otra unidad); están en agaves-pro,
  `directorio-nuevo/data/mercado/comercio-exterior/exportaciones-mexico.csv`, filtrando por `fuente`.
- El CRT no cubre mezcal; para mezcal solo hay el informe de COMERCAM.
