# Plan: agave para mezcal (DO del mezcal)

Objetivo: medir el agave cultivado para mezcal con el mismo método satelital que el del
tequila (Sentinel-2 2018–2026 y, si sirve, Landsat 2009–2017), empezando por Oaxaca.

## Por qué es más difícil que el tequila

| | Tequila (agave azul) | Mezcal |
|---|---|---|
| Especie | Una (*A. tequilana* Weber azul) | Sobre todo espadín (*A. angustifolia*); además tobalá, tepeztate, arroqueño y otros, muchos silvestres |
| Parcela típica | 5–50 ha, en hileras | 0.5–3 ha, a veces intercalada con milpa |
| Terreno | Valles y lomeríos | Valles semiáridos y laderas con pendiente fuerte |
| Vegetación vecina | Maíz, pastizal, bosque | Matorral xerófilo y selva baja, que en secas se parecen al agave |
| Ciclo | 5–7 años | Espadín 6–8 años; los silvestres no se plantan, se recolectan |
| Referencia oficial | SIAP por municipio, CRT | SIAP por municipio (Oaxaca: 12,138 ha sembradas en 2025), COMERCAM (Oaxaca: 90.7 % de la producción 2024) |

Consecuencias para el método:
- A 20 m un pixel mide 0.04 ha; una parcela de 1 ha son unos 25 pixeles, con mucha orilla
  mezclada. Conviene probar rojo e infrarrojo cercano a 10 m (Sentinel-2 los tiene).
- Landsat (30 m) probablemente no alcanza para fechar plantaciones chicas. La historia
  2009–2017 queda como opcional y solo en zonas de parcelas grandes.
- Los silvestres no tienen "fecha de plantación" y no se pueden contar con estas reglas.
  El resultado será agave **cultivado**, sobre todo espadín.
- Las reglas actuales están calibradas en Jalisco. Sin puntos de verificación en Oaxaca no
  hay forma de saber si los umbrales sirven.

## Fases

0. **Datos de referencia** (sin bajar imágenes)
   - Hecho: municipios de Oaxaca (`datos_externos/municipios_oaxaca.geojson`, 569 de 570).
   - Hecho: SIAP municipal y COMERCAM ya están en `datos_externos/`.
   - Falta: lista oficial de municipios de la DO del mezcal fuera de Oaxaca
     (Guerrero, Durango, San Luis Potosí y Zacatecas completos; partes de Guanajuato,
     Tamaulipas, Michoacán, Puebla, Morelos, Aguascalientes, Sinaloa y Estado de México).
   - Falta: **puntos de verificación** de espadín y de lo que no es agave (matorral, milpa,
     selva baja), unos 200 en la zona de prueba. Es lo que más mejora el resultado.

1. **Prueba con las reglas actuales en 14QQD** (una corrida, ~1.5 h)
   - El mosaico cubre Santiago Matatlán, Tlacolula, Miahuatlán, Ejutla y Sola de Vega.
   - Comparar por municipio contra el SIAP (Miahuatlán 1,265 ha, Matatlán 797, Tlacolula 666).
   - Solo dice qué tan lejos estamos; no se publica como resultado.

2. **Ajuste de reglas para espadín**
   - Calibrar umbrales de verdor de secas y amplitud con los puntos de verificación.
   - Probar rojo/infrarrojo a 10 m.
   - Separar matorral xerófilo (verdor estable pero más bajo y disperso) y milpa intercalada.
   - Usar la pendiente: el espadín también se planta en ladera, así que no sirve la regla
     de selva baja que se usa en Jalisco tal cual.

3. **Escalar en Oaxaca**
   - Región mezcalera: 14QQD, 14QRD, 14QPD y vecinos al sur (unos 6–8 mosaicos).
   - Mismo esquema de cola que el tequila (`cola_mosaicos.txt`, `nocturno.py`).

4. **Resto de la DO** según prioridad (Guerrero, Durango, Puebla, Michoacán, San Luis Potosí).

## Decisiones pendientes

- De dónde salen los puntos de verificación: recorridos de campo, contactos en Oaxaca,
  o marcarlos a mano sobre imágenes de alta resolución.
- Si la prueba de la fase 1 se corre ya, antes de tener puntos, solo para ver el orden de
  magnitud.
- Orden de los estados después de Oaxaca.
