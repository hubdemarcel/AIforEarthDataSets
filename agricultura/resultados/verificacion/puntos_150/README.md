# 150 puntos de verificación de agave

Puntos para marcar a mano en imagen satelital (Google Maps) si hay agave o no, en la
página "Verificar agave" (artifact de claude.ai). Las respuestas se guardan en la base de
datos de la página (colección `respuestas`, un documento por punto: `valor` = si / no /
nose y `motivo` cuando es no) y se usan como etiquetas reales para reentrenar
`modelo_espectral.py`, sobre todo en Guanajuato norte y Tamaulipas, donde las etiquetas
geográficas fallan.

`puntos_verificacion.csv` trae además la probabilidad del modelo (`p`) y la confianza de
las reglas NDVI. La página no las muestra, para no sesgar a quien marca.

Nueve zonas, mitad con p ≥ 0.5 y mitad con p < 0.5 donde alcanzó (Tamaulipas solo tiene 7
puntos con p alta).
