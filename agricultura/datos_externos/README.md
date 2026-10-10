# Datos externos

- `municipios_estados_do.geojson`: municipios de Jalisco, Guanajuato, Michoacán, Nayarit
  y Tamaulipas, de [geoBoundaries](https://www.geoboundaries.org) (gbOpen MEX ADM2,
  versión simplificada; licencia abierta, citar geoBoundaries). El campo
  `denominacion_origen` ("si"/"no") y la clave `cvegeo_inegi` vienen de cruzar por
  nombre con `do_tequila_municipios.csv` (los 181 municipios cruzan; cuatro nombres
  difieren entre fuentes: Ciudad Manuel Doblado, Briseñas de Matamoros, Régules y
  Vistahermosa).
- `precios_agave_prensa.csv`: precios aproximados del agave reportados en prensa, con
  la fuente de cada dato. No es una serie oficial.
- `do_tequila_municipios.csv`: **lista oficial de los 181 municipios con denominación de
  origen del tequila** (Jalisco completo, 125; Guanajuato 7; Michoacán 30; Nayarit 8;
  Tamaulipas 11), con su clave INEGI (`cvegeo_inegi`) para cruzarla con los polígonos.
  Fuente: Declaración General de Protección (DOF 1977 y reformas) y CRT, tomada del atlas
  del agave de agaves.pro (`hubdemarcel/agaves-pro`, `agave-atlas/data/do-tequila-municipios.inegi.json`).
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
- `PRECIOS-AGAVE.md`: resumen del precio del agave (SIAP 2003–2025 por año, estado y municipio; prensa 2026; diferencias entre fuentes).
- `ARANCELES-AGAVE.md` y `aranceles_fiscal_por_pais.json`: aranceles de importación e impuestos especiales al tequila y mezcal en 30 países (top destinos + México), con tratado con México, fuentes y nivel de confianza. Copia de `fiscal-por-pais.json` de agaves-pro (2026-10-04).
- `inpc_mensual.csv` e `inpc_anual.csv`: INPC de Banxico (SIE, serie SP1, base 2Q jul 2018 = 100), mensual 1969-01 a 2026-09, y promedio anual con `factor_a_pesos_2025` (precio en pesos de 2025 = precio corriente × factor). Se regeneran con `directorio-nuevo/data/mercado/inpc/pull_inpc.py` de agaves-pro. Deflactada, la serie del SIAP es coherente desde 1983, así que antes de 1993 ya viene en pesos nuevos.
- `DEMANDA-EXPORTACION.md`, `crt_tequila_anual.csv`, `crt_exportaciones_mensuales_por_pais.csv`, `crt_economia_tequila.json`, `comercam_economia_mezcal.json`: demanda de agave (consumo de las tequileras), producción y exportación de tequila del CRT 1995–2026 (mensual por país desde 1997) y mezcal de COMERCAM 2011–2024. Desde agaves-pro (atlas y `comercio-exterior/`).
