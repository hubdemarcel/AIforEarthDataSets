"""Clasificador espectral del agave detectado, con las 10 bandas de Sentinel-2.

Usa las muestras de pixeles que deja `humedad.py` en cada mosaico (`espectro_muestra.csv.gz`:
10 bandas en abril 2025, abril 2026 y septiembre 2025) y calcula índices (NDVI, NDMI, NDRE,
B11 vs B12, azul/rojo, pendiente del borde rojo) y su cambio de secas a lluvias.

Etiquetas por geografía, sin verificación en campo: "agave" = pixeles de agave con confianza
media o alta en el núcleo tequilero (Tequila, Amatitán, Altos); "imitadores" = pixeles que las
reglas marcan como agave en la sierra (Del Nayar, Mezquitic...), la zona aguacatera, Tierra
Caliente y Tamaulipas. Entrena un gradient boosting, lo valida dejando fuera grupos de
municipios y lo aplica a todo el agave de la muestra para estimar qué fracción de cada
municipio es agave.

Uso:
    python -m agricultura.modelo_espectral
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
SALIDA = RAIZ / "resultados" / "municipios"

def main():
    import pandas as pd, numpy as np, glob, sys
    from sklearn.metrics import roc_auc_score
    fs=sorted(glob.glob(str(RAIZ / 'resultados' / 'mosaicos' / '*' / 'espectro_muestra.csv.gz')))
    d=pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    print(len(fs),'mosaicos', len(d),'pixeles'); print(d.clase.value_counts().sort_index().to_dict())
    bandas=['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12']
    for m in ['2025-04','2026-04','2025-09']:
        b={k:d[f'{k}_{m}']/1e4 for k in bandas}
        n=lambda a,c:(b[a]-b[c])/(b[a]+b[c])
        d[f'ndvi_{m}']=n('B08','B04'); d[f'ndmi_{m}']=n('B08','B11'); d[f'ndre_{m}']=n('B8A','B05')
        d[f'nbr2_{m}']=n('B11','B12'); d[f'azulrojo_{m}']=b['B02']/b['B04']; d[f'repend_{m}']=(b['B07']-b['B05'])/b['B05']
        d[f'gcvi_{m}']=b['B08']/b['B03']-1
    for k in ['ndvi','ndmi','ndre','nbr2','azulrojo','repend','gcvi']+bandas:
        d[f'{k}_cambio']=d[f'{k}_2025-09']-d[f'{k}_2025-04']
    core=['Tequila','Amatitán','Arandas','Tepatitlán de Morelos','Atotonilco el Alto','Jesús María','Ayotlán','Degollado','El Arenal','Magdalena','San Ignacio Cerro Gordo','Tototlán']
    grupos={'sierra':['Del Nayar','Mezquitic','La Yesca','Bolaños','Huejuquilla el Alto','Huajicori'],
     'aguacate':['Tancítaro','Uruapan','Peribán','Los Reyes','Tingüindín','Salvador Escalante','Ziracuaretiro','Tacámbaro'],
     'tierra_caliente':['Buenavista','Apatzingán','Tepalcatepec','Parácuaro','Aguililla'],
     'tamaulipas':None}
    a4=d.clase==4
    lab=pd.Series('',index=d.index)
    lab[a4&d.municipio.isin(core)&(d.confianza>=2)]='agave'
    for g,l in grupos.items():
        lab[a4&((d.estado=='Tamaulipas') if l is None else d.municipio.isin(l))]=g
    d['etiqueta']=lab
    print(d.etiqueta.value_counts().to_dict())
    feats=[c for c in d.columns if any(c.endswith(s) for s in ['2025-04','2026-04','2025-09','cambio'])]
    res={}
    for g in grupos:
        s=d[d.etiqueta.isin(['agave',g])]
        y=(s.etiqueta=='agave').astype(int)
        res[g]={f:abs(roc_auc_score(y,s[f].fillna(s[f].median()))-0.5)+0.5 for f in feats}
    r=pd.DataFrame(res); r['media']=r.mean(1)
    pd.set_option('display.width',200)
    print(r.sort_values('media',ascending=False).head(25).round(3))
    r.round(3).to_csv(SALIDA / 'separacion_bandas_agave.csv')
    
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    feats=[c for c in d.columns if any(c.endswith(s) for s in ['2025-04','2026-04','2025-09','cambio'])]
    L=d[d.etiqueta!=''].copy(); L['y']=(L.etiqueta=='agave').astype(int)
    # Validación: dejar fuera un municipio a la vez (agave) y un grupo de imitadores a la vez
    from sklearn.model_selection import GroupKFold
    mun=L.municipio.fillna('?').values
    pred=np.full(len(L),np.nan)
    for tr_i,te_i in GroupKFold(5).split(L,L.y,mun):
        tr=np.zeros(len(L),bool); tr[tr_i]=True; te=~tr
        m=HistGradientBoostingClassifier(max_iter=200,learning_rate=0.08,random_state=0).fit(L[feats][tr],L.y[tr])
        pred[te]=m.predict_proba(L[feats][te])[:,1]
    L['p']=pred
    print('AUC municipio fuera:',round(roc_auc_score(L.y,L.p),3))
    for g,s in L.groupby('etiqueta'): print(g, 'p>0.5:',round((s.p>0.5).mean(),3), 'n',len(s))
    m=HistGradientBoostingClassifier(max_iter=200,learning_rate=0.08,random_state=0).fit(L[feats],L.y)
    # importancia por permutación rápida
    from sklearn.inspection import permutation_importance
    sub=L.sample(8000,random_state=0)
    pi=permutation_importance(m,sub[feats],sub.y,n_repeats=3,random_state=0,scoring='roc_auc')
    imp=pd.Series(pi.importances_mean,index=feats).sort_values(ascending=False)
    print(imp.head(12).round(4))
    # aplicar a todo el agave (clase 4)
    A=d[d.clase==4].copy(); A['p']=m.predict_proba(A[feats])[:,1]
    f=A.groupby(['estado','municipio']).p.agg(fraccion_agave=lambda s:(s>0.5).mean(), pixeles_muestra='size')
    j=pd.read_csv(SALIDA / 'agave_por_municipio_y_anio.csv').set_index(['estado','municipio']).agave_en_pie_ha
    t=f.join(j,how='inner'); t['agave_joven_filtrado_ha']=(t.agave_en_pie_ha*t.fraccion_agave).round()
    t.round(3).to_csv(SALIDA / 'agave_joven_filtrado_modelo.csv')
    print(t.groupby(level=0)[['agave_en_pie_ha','agave_joven_filtrado_ha']].sum())


if __name__ == '__main__':
    main()
