# Datos externos

- `municipios_estados_do.geojson`: municipios de Jalisco, Guanajuato, Michoacán, Nayarit
  y Tamaulipas, de [geoBoundaries](https://www.geoboundaries.org) (gbOpen MEX ADM2,
  versión simplificada; licencia abierta, citar geoBoundaries). El campo
  `denominacion_origen` marca "si" para Jalisco (todo el estado está en la DO del
  tequila) y "por confirmar" para el resto hasta tener la lista oficial de la
  Declaración General de Protección.
- `precios_agave_prensa.csv`: precios aproximados del agave reportados en prensa, con
  la fuente de cada dato. No es una serie oficial.
- `do_tequila_municipios.csv`: **lista oficial de los 181 municipios con denominación de
  origen del tequila** (Jalisco completo, 125; Guanajuato 7; Michoacán 30; Nayarit 8;
  Tamaulipas 11), con su clave INEGI (`cvegeo_inegi`) para cruzarla con los polígonos.
  Fuente: Declaración General de Protección (DOF 1977 y reformas) y CRT, tomada del atlas
  del agave de agaves.pro (`hubdemarcel/agaves-pro`, `agave-atlas/data/do-tequila-municipios.inegi.json`).
  Con esto se puede cambiar el «por confirmar» de `municipios_estados_do.geojson`.
- `siap_agave_municipal.csv`, `siap_agave_estatal.csv`, `siap_agave_resumen.csv`: Cierre de
  la producción agrícola del SIAP (Secretaría de Agricultura), datos abiertos de
  https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php (el dominio viejo
  `nube.siap.gob.mx` ya no existe). Municipal 2003–2025, estatal 1980–2002, y un resumen por
  año, estado y cultivo con el **precio medio rural ponderado** (pesos por tonelada).
  Usar el cultivo `Agave` para el de tequila y mezcal; los magueyes y el henequén vienen
  aparte. Son pesos corrientes (deflactar con INPC) y antes de 1993 pueden estar en pesos
  viejos. Se regeneran con `directorio-nuevo/data/mercado/siap/pull_siap.py` de agaves-pro.
  Serie oficial que complementa a `precios_agave_prensa.csv` (ojo: prensa da pesos por kg,
  el SIAP pesos por tonelada).
