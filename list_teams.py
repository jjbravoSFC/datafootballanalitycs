import pandas as pd
import glob

files = glob.glob('CSVs/TemporadasClasificaciones/*.csv')
dfs = []
for f in files:
    try:
        dfs.append(pd.read_csv(f, sep=';', encoding='utf-8'))
    except:
        dfs.append(pd.read_csv(f, sep=';', encoding='latin1'))

df = pd.concat(dfs)
equipos = sorted(df['Equipo'].unique().tolist())
for e in equipos:
    print(repr(e))
