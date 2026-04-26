import pandas as pd
import sys
sys.path.insert(0, r"c:\OneDrive\OneDrive\Desarrollos Locales\Temporadas Clasificaciones")
from app import load_data
import os

df_clas = load_data()
df_clas = df_clas[['Temporada', 'Jornada', 'Equipo', 'GF', 'GC', 'TA', 'TR']].copy()
df_clas = df_clas.sort_values(['Temporada', 'Equipo', 'Jornada'])

cols_to_diff = ['GF', 'GC', 'TA', 'TR']
df_diff = df_clas.groupby(['Temporada', 'Equipo'])[cols_to_diff].diff().fillna(df_clas[cols_to_diff])

for col in cols_to_diff:
    df_clas[f'{col}_partido'] = df_diff[col]

print("Clasificacion Delta Test for a specific team (Barcelona, 2024-2025):")
print(df_clas[(df_clas['Equipo'].str.contains('Barcelona')) & (df_clas['Temporada'] == '2024-2025')].head(5))

target_dir = os.path.join("CSVs", "TemporadasPartidos")
partidos_list = []
if os.path.exists(target_dir):
    for f in os.listdir(target_dir):
        if f.endswith(".csv"):
            df_p = pd.read_csv(os.path.join(target_dir, f), sep=';', encoding='latin1')
            season = f.replace(".csv", "")
            df_p['Temporada'] = season
            partidos_list.append(df_p)

df_partidos = pd.concat(partidos_list, ignore_index=True)
df_partidos['Arbitro'] = df_partidos['Arbitro'].astype(str).str.strip()
df_partidos = df_partidos[df_partidos['Arbitro'] != 'nan']
df_partidos['Jornada'] = pd.to_numeric(df_partidos['Jornada'], errors='coerce')

df_local = pd.merge(df_partidos[['Temporada', 'Jornada', 'Local', 'Visitante', 'Arbitro', 'GL', 'GV']], 
                    df_clas, 
                    left_on=['Temporada', 'Jornada', 'Local'], 
                    right_on=['Temporada', 'Jornada', 'Equipo'], 
                    how='inner')
df_local['Condicion'] = 'Local'

df_vis = pd.merge(df_partidos[['Temporada', 'Jornada', 'Local', 'Visitante', 'Arbitro', 'GL', 'GV']], 
                  df_clas, 
                  left_on=['Temporada', 'Jornada', 'Visitante'], 
                  right_on=['Temporada', 'Jornada', 'Equipo'], 
                  how='inner')
df_vis['Condicion'] = 'Visitante'

df_refs = pd.concat([df_local, df_vis], ignore_index=True)

print("Merged Test for a referee (Mateo Busquets):")
print(df_refs[df_refs['Arbitro'].str.contains('Mateo Busquets')].head(5)[['Temporada', 'Jornada', 'Local', 'Visitante', 'Equipo', 'TA_partido', 'TR_partido']])
