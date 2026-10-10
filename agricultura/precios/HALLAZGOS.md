# Modelo de precio del agave: primera prueba (2026-10-10)

Datos: precio medio rural nacional SIAP (cultivo Agave) deflactado con INPC a pesos de 2025;
demanda = agave consumido por tequileras (CRT); oferta = superficie en pie SIAP. Serie anual 1997–2025.

## Resultados
- Relación de nivel: log(precio real) contra log(demanda / superficie en pie de hace L años).
  La correlación es máxima con L = 3 (0.73) y baja a cero con L = 7. R² del ajuste: 0.53.
- Validación con origen móvil (entrenar hasta Y−1, predecir Y, 2008–2025):

| Modelo | Error medio | Dirección acertada |
|---|---|---|
| Demanda / superficie de hace 3 años | 59 % | 7 de 18 |
| Lo anterior + precio del año previo | 39 % | 6 de 18 |
| Solo el precio del año previo (ingenuo) | 35 % | 9 de 18 |

Ningún modelo simple con datos oficiales anuales le gana al ingenuo. No predice ni el arranque
de 2014–2018 ni la caída de 2025.

## Por qué
- La superficie en pie del SIAP mezcla todas las edades, salta por registro (−64 % en 1998, +66 % en
  2023) y no dice cuándo se plantó cada hectárea, que es lo que define cuándo llega a jima.
- El precio SIAP es de lo cosechado en el año, con contratos firmados antes; va ~1 año detrás del
  precio de calle (ver `datos_externos/PRECIOS-AGAVE.md`).
- Son ~30 puntos anuales y 3 ciclos.

## Siguiente paso
La pieza que falta es la oferta por **año de plantación** (cohortes) para toda la denominación de
origen, que es justo lo que da el satélite (`agave.plantaciones`, `serie_historica.py`). Con eso:
oferta que llega a 6–7 años en cada año, contra demanda CRT; y el precio de calle (prensa,
destilerías) además del SIAP.

## Con el precio de mercado de Tequila Matchmaker (1996–2024)
Es la serie medida de 8 destilerías (marcas participantes); se usa como precio objetivo principal del modelo.
- El precio SIAP sigue al de mercado con ~1 año de rezago: correlación de logaritmos 0.87 sin rezago y
  0.91 con 1 año. Confirma que el SIAP refleja contratos ya firmados.
- Con el precio de mercado como objetivo, los modelos simples de demanda / superficie SIAP tampoco le ganan
  al ingenuo (errores de 85 % y 57 % contra 36 %; dirección 7, 4 y 11 de 17).
- Su proyección (ene-2024) da 2.4–3.6 $/kg en 2026–2032, con mínimo en 2028. Coincide con el pico de
  agave que llega a jima en Valles según el satélite (2028–2029).

## Confianza del agave detectado vs SIAP 2025 (31 municipios con cobertura completa y > 300 ha)
`confianza.py` califica cada pixel de agave por su amplitud después de plantar (umbrales tomados de los 9
agaves confirmados en Tequila). Total: alta confianza 40,120 ha; con media y baja 59,205 ha; SIAP 25,237 ha.
- Correlación entre municipios (log): 0.61. Muchos municipios cuadran con el SIAP (Zacoalco 1.0×, San Cristóbal
  1.1×, Ixtlahuacán de los Membrillos y Tecolotlán 1.2×, Jocotepec 0.6×).
- Los excesos se concentran en la zona metropolitana (Tlajomulco 5.0×, Zapopan 3.1×, Ixtlahuacán del Río 3.3×)
  y en Ameca (4.0×), Atoyac (4.4×) y El Arenal (3.4×). Hipótesis: terrenos baldíos o pastizales periurbanos que se
  limpian y se regeneran imitan la firma del agave. Hay que verificar ahí.

## Con el precio de mercado (8 destilerías) y la siembra por satélite de la zona piloto (1993–2024)
- La siembra responde al precio real con ~2 años de retraso: correlación 0.47 (mismo año), 0.55 (1 año),
  **0.61 (2 años)**, 0.53 (3 años). Promedio móvil de 3 años de hectáreas plantadas.
- La oferta que llega (siembra de hace 4–6 años) se relaciona negativamente con el precio (−0.32), débil.
- log precio = 1.32 + 1.52 log demanda CRT − 1.22 log oferta(4–6 años); R² 0.30. Validación 2010–2024: acierta
  la dirección 10 de 15 años, error medio 67 %. Signos correctos; la oferta de una zona de 380 km² no basta.

## Pendiente para el final: filtro de zona urbana
Agave detectado a menos de 500 m de zona urbana: Tequila 6 %, Amatitán 5 %, Tlajomulco 22 %, Zapopan 25 %,
Zacoalco 16 %, Ameca 3 %, Teuchitlán 2 %. Ayudaría en la zona metropolitana, no en Ameca.

## Historia 1993–2024 del mosaico completo 13QFD (Valles, ~12,000 km²)
Landsat 1993–2017 + Sentinel-2 2018–2026, homologando cada año de Landsat contra los campos de cultivo anual
(los saltos entre sensores creaban plantaciones falsas: bosque en secas 0.33–0.40 con Landsat 5/7 y 0.44–0.49
con Landsat 8). Tras homologar, 2011 bajó de 35,957 a 4,626 ha y 2013 de 36,632 a 9,028 ha.

La serie sigue los ciclos a simple vista (ola 2000–2003, siembra baja 2005–2010, subida 2013–2017, ola
2021–2023), pero **estadísticamente no mejora el modelo**:
- Respuesta de la siembra al precio de mercado: 0.32 (mismo año), 0.18 (1 año), −0.01 (2 años).
- Precio contra oferta que llega (siembra de hace 3–8 años): correlaciones entre −0.03 y 0.05.
- Modelos demanda + oferta: error 52–88 % y dirección 8–11 de 15; con precio previo, error 66–98 %.
  El ingenuo ("igual que el año pasado") tiene error 38 %.

Lectura: con lo que hay hoy, la oferta medida por satélite en una sola región no predice el precio año por año.
Posibles razones, en orden de sospecha: (1) falsos positivos (pastizales y terrenos que imitan la firma, ver
comparación con SIAP); (2) Valles es una parte de la oferta, Los Altos pesa más; (3) el precio responde a
cambios de régimen (escasez ↔ sobreoferta), no a variaciones anuales finas; (4) 28 datos anuales.
