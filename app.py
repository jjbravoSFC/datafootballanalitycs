import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import glob
import re
import os
import io
import openai
import base64
from streamlit_option_menu import option_menu

def read_csv_dynamic(path, sep=";"):
    try:
        df = pd.read_csv(path, sep=sep, encoding="utf-8")
        return df
    except UnicodeDecodeError:
        return pd.read_csv(path, sep=sep, encoding="latin1")

# --- Configuración de la página ---
st.set_page_config(page_title="Analizador Histórico de Fútbol", layout="wide")

# --- Funciones de Carga de Datos ---
@st.cache_data
def load_data():
    search_path = os.path.join("CSVs", "TemporadasClasificaciones", "Temporadas Clasificaciones.xlsx - [*.csv")
    all_files = glob.glob(search_path)
    
    if not all_files:
        # Fallback check for brackets logic if glob fails or is weird on windows
        target_dir = os.path.join("CSVs", "TemporadasClasificaciones")
        if os.path.exists(target_dir):
            all_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.startswith("Temporadas Clasificaciones.xlsx - [") and f.endswith("].csv")]
    
    if not all_files:
        return pd.DataFrame()

    df_list = []
    
    for filename in all_files:
        try:
            # Extraer temporada del nombre del archivo
            match = re.search(r'\[(\d{4}-\d{4})\]', filename)
            if match:
                season = match.group(1)
            else:
                continue

            df = pd.read_csv(filename, sep=";")
            
            # Limpieza básica
            # Filtrar filas donde 'Pos' no sea numérico (eliminar notas al pie)
            df = df[pd.to_numeric(df['Pos'], errors='coerce').notnull()]
            
            # Asegurar tipos
            df['Pos'] = pd.to_numeric(df['Pos'], errors='coerce')
            
            # Limpiar PTS de asteriscos u otros caracteres
            df['PTS'] = df['PTS'].astype(str).str.extract(r'(\d+)', expand=False)
            df['PTS'] = pd.to_numeric(df['PTS'], errors='coerce').fillna(0).astype(int)
            
            # Limpiar y convertir resto de métricas
            cols_to_int = ['PG', 'PE', 'PP', 'GF', 'GC', 'TA', 'TR']
            for col in cols_to_int:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

            # Filtrar filas donde 'Pos' no sea numérico (eliminar notas al pie)
            df = df[df['Pos'].notnull()]
            df['Pos'] = df['Pos'].astype(int)
            
            # Añadir columna temporada
            df['Temporada'] = season

            # Crear columna Jornada basada en la estructura del archivo (bloques de clasificación)
            # El archivo tiene bloques secuenciales de jornadas (J1, J2, J3...)
            # Detectamos el cambio de jornada cuando 'Pos' es menor que el anterior (ej: pasa de 20 a 1)
            # o usamos un método vectorial eficiente
            
            # Identificar inicios de bloque: True donde Pos < Pos anterior
            # shift(1) mueve todo uno abajo. fill_value=1000 para que la primera fila (Pos 1) sea < 1000 -> True (Nueva Jornada)
            # Pero queremos que la primera fila sea Jornada 1.
            # Pos anterior:
            # 1, 2, ... 20, 1, 2...
            # shift:
            # ?, 1, ... 19, 20, 1...
            # Condicion: Pos <= Pos_prev? No siempre, a veces hay empates.
            # Mejor criterio: La posición suele reiniciar a 1.
            # O simplemente: Cada vez que encontramos un '1' en la columna Pos, podría ser nueva jornada?
            # Cuidado con empates en el puesto 1 (muy raro pero posible).
            # Mejor: cada vez que el índice de Pos disminuye drásticamente.
            
            # En pandas vectorizado:
            # Detectar reinicios: (df['Pos'] < df['Pos'].shift(1, fill_value=100))
            # cumsum() nos da el ID de grupo.
            
            # Ajuste robusto:
            # Asumimos que la primera fila es J1.
            # Cada vez que vemos un '1' en la columna 'Pos' DESPUÉS de haber visto números mayores, es una nueva jornada.
            # Pero simplifiquemos: (Pos < Pos_anterior) suele funcionar bien pque siempre vuelves al 1.
            s_shifted = df['Pos'].shift(1, fill_value=999)
            df['Jornada'] = (df['Pos'] < s_shifted).cumsum()
            
            # NOTA: Ya no eliminamos duplicados para mantener todas las jornadas
            # df = df.drop_duplicates(subset=['Equipo'], keep='last')
            
            df_list.append(df)
        except Exception as e:
            st.error(f"Error cargando archivo {filename}: {e}")

    if df_list:
        full_df = pd.concat(df_list, ignore_index=True)
        
        # Excepción Temporada 2025-2026: J33 del calendario se jugó ANTES que J32.
        # El CSV tiene bloques secuenciales: el bloque 32 ES la J33 real del calendario,
        # y el bloque 33 (cuando se añada) será la J32 real.
        # Renombramos Jornada para que coincida con el número real del calendario.
        mask_2526 = full_df['Temporada'] == '2025-2026'

        # Calcular máscaras ANTES de hacer ningún rename (importante el orden)
        mask_bloque32 = mask_2526 & (full_df['Jornada'] == 32)  # → real J33
        mask_bloque33 = mask_2526 & (full_df['Jornada'] == 33)  # → real J32 (cuando exista)

        # Aplicar renames: bloque 32 pasa a llamarse J33, bloque 33 pasa a J32
        full_df.loc[mask_bloque32, 'Jornada'] = 33
        full_df.loc[mask_bloque33, 'Jornada'] = 32

        # Orden_Cronologico: slot de juego real
        # J33 (del calendario) se jugó en la posición 32 → OC=32
        # J32 (del calendario) se jugará en la posición 33 → OC=33
        # Para el resto de temporadas y jornadas, OC == Jornada
        full_df['Orden_Cronologico'] = full_df['Jornada']
        mask_j33_cal = mask_2526 & (full_df['Jornada'] == 33)
        mask_j32_cal = mask_2526 & (full_df['Jornada'] == 32)
        full_df.loc[mask_j33_cal, 'Orden_Cronologico'] = 32
        full_df.loc[mask_j32_cal, 'Orden_Cronologico'] = 33

        # Ordenar cronológicamente: temporada, orden real de juego, posición
        full_df = full_df.sort_values(by=['Temporada', 'Orden_Cronologico', 'Pos'])
        return full_df
    else:
        return pd.DataFrame()

@st.cache_data
def load_referees_data():
    """Reads matches and standings to calculate match-level referee statistics."""
    df_clas = load_data()
    if df_clas.empty:
        return pd.DataFrame()
        
    df_clas = df_clas[['Temporada', 'Jornada', 'Orden_Cronologico', 'Equipo', 'GF', 'GC', 'TA', 'TR']].copy()
    df_clas = df_clas.sort_values(['Temporada', 'Equipo', 'Orden_Cronologico'])

    cols_to_diff = ['GF', 'GC', 'TA', 'TR']
    df_diff = df_clas.groupby(['Temporada', 'Equipo'])[cols_to_diff].diff().fillna(df_clas[cols_to_diff])

    for col in cols_to_diff:
        df_clas[f'{col}_partido'] = df_diff[col]

    target_dir = os.path.join("CSVs", "TemporadasPartidos")
    partidos_list = []
    if os.path.exists(target_dir):
        for f in os.listdir(target_dir):
            if f.endswith(".csv"):
                try:
                    df_p = read_csv_dynamic(os.path.join(target_dir, f), sep=';')
                    season = f.replace(".csv", "")
                    df_p['Temporada'] = season
                    partidos_list.append(df_p)
                except Exception:
                    pass

    if not partidos_list:
        return pd.DataFrame()

    df_partidos = pd.concat(partidos_list, ignore_index=True)
    if 'Arbitro' not in df_partidos.columns:
        return pd.DataFrame()

    df_partidos['Arbitro'] = df_partidos['Arbitro'].astype(str).str.strip()
    df_partidos = df_partidos[df_partidos['Arbitro'] != 'nan']
    df_partidos['Jornada'] = pd.to_numeric(df_partidos['Jornada'], errors='coerce')

    # Join para Local
    df_local = pd.merge(df_partidos[['Temporada', 'Jornada', 'Local', 'Visitante', 'Arbitro', 'GL', 'GV']], 
                        df_clas, 
                        left_on=['Temporada', 'Jornada', 'Local'], 
                        right_on=['Temporada', 'Jornada', 'Equipo'], 
                        how='inner')
    df_local['Condicion'] = 'Local'

    # Join para Visitante
    df_vis = pd.merge(df_partidos[['Temporada', 'Jornada', 'Local', 'Visitante', 'Arbitro', 'GL', 'GV']], 
                      df_clas, 
                      left_on=['Temporada', 'Jornada', 'Visitante'], 
                      right_on=['Temporada', 'Jornada', 'Equipo'], 
                      how='inner')
    df_vis['Condicion'] = 'Visitante'

    df_refs = pd.concat([df_local, df_vis], ignore_index=True)
    return df_refs


# --- Funciones para Estudio LaLiga ---

def get_teams_list():
    """Retorna la lista de equipos disponibles en CSVs/Equipos."""
    equipos_path = os.path.join("CSVs", "Equipos")
    if not os.path.exists(equipos_path):
        return []
    return [d for d in os.listdir(equipos_path) if os.path.isdir(os.path.join(equipos_path, d))]

def parse_match_metadata(filename):
    """
    Extrae rival y fecha del nombre del archivo.
    """
    basename = os.path.basename(filename)
    try:
        parts = basename.split("_stats_")[0]
        return parts.replace("-", " ")
    except:
        return basename

@st.cache_data
def load_team_match_stats(team_name):
    """
    Carga todas las estadísticas de resumen de un equipo.
    Devuelve un DataFrame con una fila por partido.
    """
    team_path = os.path.join("CSVs", "Equipos", team_name)
    all_files = glob.glob(os.path.join(team_path, "*_summary.csv"))
    
    match_stats = []
    
    for f in all_files:
        try:
            # Leemos el header múltiple
            df = pd.read_csv(f, header=[0, 1])
            
            # Aplanamos columnas
            df_flat = df.copy()
            df_flat.columns = ['_'.join(col).strip() for col in df.columns.values]
            
            # Buscamos la columna Player
            player_cols = [c for c in df_flat.columns if 'Player' in c]
            if not player_cols: continue
            player_col = player_cols[0]
            
            # Filtramos la fila de totales ("Players")
            total_row = df_flat[df_flat[player_col].astype(str).str.contains("Players", case=False, na=False)]
            
            if not total_row.empty:
                row_data = total_row.iloc[0].to_dict()
                row_data['Match'] = parse_match_metadata(f)
                match_stats.append(row_data)
        except Exception:
            continue
            
    if not match_stats:
        return pd.DataFrame()
        
    return pd.DataFrame(match_stats)

def _get_metric_type(metric_name):
    """Devuelve 'high_good' o 'low_good'."""
    # Métricas donde MENOS es MEJOR
    low_good = ['Performance_CrdY', 'Performance_CrdR', 'Performance_Fls', 'Performance_PKcon', 'Performance_OG', 'Performance_GC'] # GC no suele estar en summary, pero por si acaso
    if any(x in metric_name for x in low_good):
        return 'low_good'
    return 'high_good'

def analyze_team_performance(team_name, df_matches, league_averages=None):
    """
    Calcula medias, tendencias y virtudes/defectos.
    """
    if df_matches.empty:
        return None

    # Mapeo de columnas relevantes del CSV summary
    # Performance: Gls, Ast, Sh, SoT, CrdY, CrdR, Tkl, Int, Blocks
    # Expected: xG, npxG
    # Passes: Cmp, Att, Cmp%
    # Carries: Carries
    
    # Nombre en CSV Flat -> Etiqueta Legible
    cols_map = {
        'Performance_Gls': 'Goles',
        'Performance_Ast': 'Asistencias',
        'Performance_Sh': 'Tiros',
        'Performance_SoT': 'Tiros a Puerta',
        'Expected_xG': 'xG (Esperados)',
        'Passes_Cmp%': '% Pase',
        'Performance_Tkl': 'Entradas',
        'Performance_Int': 'Intercepciones',
        'Performance_Blocks': 'Bloqueos',
        'Performance_CrdY': 'Tarjetas Amarillas',
        'Performance_CrdR': 'Tarjetas Rojas'
    }
    
    stats_data = {}
    valid_cols = []
    
    # Preprocesamiento de columnas numéricas
    for col in cols_map.keys():
        col_candidates = [c for c in df_matches.columns if col in c] # Match exact or close
        # En df_flat es exacto 'Performance_Gls' si coinciden niveles.
        # En el CSV visto: Performance_Gls existe.
        if col in df_matches.columns:
            df_matches[col] = pd.to_numeric(df_matches[col], errors='coerce').fillna(0)
            valid_cols.append(col)

    if not valid_cols:
        return None

    # 1. Medias
    averages = df_matches[valid_cols].mean().to_dict()
    
    # 2. Tendencias (Comparar últimos 5 vs Media Global del equipo)
    # Asumimos orden por el nombre de archivo que suele incluir fecha o es cronológico en listdir si la fecha está bien formato.
    # Sino, es una aproximación.
    recent_matches = df_matches.tail(5)
    recent_avgs = recent_matches[valid_cols].mean().to_dict()
    
    analysis = {}
    
    for col in valid_cols:
        label = cols_map[col]
        avg = averages[col]
        rec = recent_avgs[col]
        metric_type = _get_metric_type(col)
        
        # Tendencia
        if avg == 0:
            change = 0
        else:
            change = (rec - avg) / avg
            
        trend_status = "Estable"
        if change > 0.10: # +10%
             trend_status = "Mejorando 📈" if metric_type == 'high_good' else "Empeorando 📉"
        elif change < -0.10: # -10%
             trend_status = "Empeorando 📉" if metric_type == 'high_good' else "Mejorando 📈"
             
        # Virtud/Defecto (Comparando con Liga si existe)
        rating = "Normal"
        if league_averages and col in league_averages:
            league_avg = league_averages[col]
            diff_league = (avg - league_avg) / league_avg if league_avg > 0 else 0
            
            if metric_type == 'high_good':
                if diff_league > 0.20: rating = "Virtud Superior 🌟" # +20% sobre liga
                elif diff_league > 0.10: rating = "Bueno ✅"
                elif diff_league < -0.20: rating = "Problema Crítico ⚠️"
                elif diff_league < -0.10: rating = "Debilidad 🔻"
            else: # Low is good (Cards)
                if diff_league > 0.20: rating = "Problema Crítico ⚠️" # Muchas tarjetas
                elif diff_league > 0.10: rating = "Debilidad 🔻"
                elif diff_league < -0.20: rating = "Virtud Superior 🌟" # Muy pocas tarjetas
                elif diff_league < -0.10: rating = "Bueno ✅"

        analysis[label] = {
            'Media': avg,
            'Tendencia': trend_status,
            'Recent': rec,
            'Rating': rating
        }
        
    return analysis

@st.cache_data
def get_league_averages():
    """Calcula la media de todos los equipos en todas las métricas para establecer baseline."""
    teams = get_teams_list()
    all_summaries = []
    
    # Muestreo para no tardar una eternidad: coger 5 equipos aleatorios o todos si son pocos.
    # Son 20 equipos, se puede hacer todos.
    for t in teams:
        df = load_team_match_stats(t)
        if not df.empty:
            all_summaries.append(df)
            
    if not all_summaries:
        return {}
        
    full_df = pd.concat(all_summaries)
    
    # Columnas numéricas de interés
    cols_map = {
        'Performance_Gls', 'Performance_Ast', 'Performance_Sh', 'Performance_SoT',
        'Expected_xG', 'Passes_Cmp%', 'Performance_Tkl', 
        'Performance_Int', 'Performance_Blocks', 'Performance_CrdY', 'Performance_CrdR'
    }
    
    avgs = {}
    for col in cols_map:
        if col in full_df.columns:
            full_df[col] = pd.to_numeric(full_df[col], errors='coerce').fillna(0)
            avgs[col] = full_df[col].mean()
            
    return avgs

# --- Vistas de la Aplicación ---

def render_home(df):
    st.markdown("<h2><i class='bi bi-house'></i> Bienvenido al Panel de Análisis Histórico</h2>", unsafe_allow_html=True)
    st.info("Utiliza el menú de la izquierda para navegar entre las diferentes herramientas de análisis.")
    
    # Calcular ultima jornada de la ultima temporada para mostrar info
    last_season = df['Temporada'].max()
    last_season_data = df[df['Temporada'] == last_season]
    last_matchweek = last_season_data['Jornada'].max() if not last_season_data.empty else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Temporadas Registradas", df['Temporada'].nunique() if not df.empty else 0)
    with col2:
        st.metric("Total Equipos Únicos", df['Equipo'].nunique() if not df.empty else 0)
    with col3:
        st.metric("Última Actualización", f"Temp. {last_season} - J{last_matchweek}")

@st.cache_data(show_spinner="Generando imagen combinada...")
def generate_combined_chart_image_cached(team_data, selected_jornada, selected_team):
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go
    
    metrics = ['Pos', 'PTS', 'PG', 'PE', 'PP', 'GF', 'GC', 'TA', 'TR']
    metric_map = {
        'Pos': 'Posición (Pos)', 'PTS': 'Puntos (PTS)', 'PG': 'Partidos Ganados (PG)',
        'PE': 'Partidos Empatados (PE)', 'PP': 'Partidos Perdidos (PP)',
        'GF': 'Goles a Favor (GF)', 'GC': 'Goles en Contra (GC)',
        'TA': 'Tarjetas Amarillas (TA)', 'TR': 'Tarjetas Rojas (TR)'
    }
    titles = [f"Evolución de {metric_map[m]}" for m in metrics]
    
    fig = make_subplots(rows=3, cols=3, subplot_titles=titles, vertical_spacing=0.15, horizontal_spacing=0.08)
    
    card_color = '#ffffff'
    
    for i, m in enumerate(metrics):
        row = (i // 3) + 1
        col = (i % 3) + 1
        
        sorted_data = team_data.sort_values('Temporada')
        
        fig.add_trace(go.Scatter(
            x=sorted_data['Temporada'],
            y=sorted_data[m],
            mode='lines+markers',
            name=m,
            line=dict(color="#38bdf8", width=3),
            marker=dict(size=8, color="#38bdf8")
        ), row=row, col=col)
        
        fig.add_trace(go.Scatter(
            x=sorted_data['Temporada'],
            y=sorted_data[m],
            mode='text',
            name=m,
            text=sorted_data[m],
            textposition="top center",
            textfont=dict(color="#f87171", size=12),
            showlegend=False
        ), row=row, col=col)
        
        if m == 'Pos':
            fig.update_yaxes(autorange="reversed", row=row, col=col)
            
        fig.update_xaxes(showgrid=False, tickangle=-45, row=row, col=col)
        fig.update_yaxes(showgrid=True, gridcolor="#e2e8f0", row=row, col=col)
        
    fig.update_layout(
        title_text=f"Análisis Histórico Completo - {selected_team} (Jornada {selected_jornada})",
        title_font=dict(color="#0f172a", size=32),
        title_x=0.5,
        paper_bgcolor=card_color,
        plot_bgcolor=card_color,
        font=dict(color="#0f172a", size=14),
        showlegend=False,
        width=2400,
        height=1400,
        margin=dict(t=120, b=80, l=50, r=50)
    )
    
    try:
        return fig.to_image(format="png")
    except Exception as e:
        print("Error generating combined image:", e)
        return None

def render_historical_analysis(df):
    st.markdown("<h2><i class='bi bi-bar-chart-line'></i> Análisis Histórico por Equipo</h2>", unsafe_allow_html=True)
    st.markdown("---")
    
    # --- Lógica para determinar la jornada por defecto ---
    # "La ultima jornada de la ultima temporada que tengamos"
    last_season = df['Temporada'].max()
    max_jornada_global = df['Jornada'].max()
    
    if last_season:
        last_season_df = df[df['Temporada'] == last_season]
        default_jornada = int(last_season_df['Jornada'].max())
    else:
        default_jornada = int(max_jornada_global) if not pd.isna(max_jornada_global) else 38

    # Slider para seleccionar Jornada
    # Usamos max_jornada_global como límite superior (e.g. 42 en temporadas antiguas)
    selected_jornada = st.slider("Comparar datos en la Jornada:", 1, int(max_jornada_global), value=default_jornada)
    
    # Filtrar el dataframe global por esa jornada
    # Nota: Si una temporada no tiene esa jornada (e.g. seleccionas J40 y la temp tiene 38), aparecerá vacía para esa temp.
    df_filtered_by_jornada = df[df['Jornada'] == selected_jornada]

    # Selector de Equipo
    equipos_unicos = sorted(df['Equipo'].unique())
    selected_team = st.selectbox("Selecciona un Equipo:", equipos_unicos, index=0)
    
    # Filtrar datos del equipo (sobre el DF ya filtrado por jornada)
    team_data = df_filtered_by_jornada.copy() # Ya estaba filtrado por jornada
    team_data = team_data[team_data['Equipo'] == selected_team]
    
    # Selector de Métrica
    metric_map = {
        'Pos': 'Posición (Pos)',
        'PTS': 'Puntos (PTS)',
        'PG': 'Partidos Ganados (PG)',
        'PE': 'Partidos Empatados (PE)',
        'PP': 'Partidos Perdidos (PP)',
        'GF': 'Goles a Favor (GF)',
        'GC': 'Goles en Contra (GC)',
        'TA': 'Tarjetas Amarillas (TA)',
        'TR': 'Tarjetas Rojas (TR)'
    }
    
    options = ['Todos'] + list(metric_map.keys())
    selected_option = st.selectbox("Métrica a visualizar:", options, 
                                   format_func=lambda x: "Todas las Métricas" if x == 'Todos' else metric_map[x])
    
    if not team_data.empty:
        
        def create_chart(data, metric, title):
            # Ordenamos por temporada para que la línea salga bien
            data = data.sort_values('Temporada')
            
            # Ajuste de colores
            # Usamos un template oscuro y personalizamos fondo
            fig = px.line(data, x='Temporada', y=metric, 
                          title=title,
                          markers=True, text=metric,
                          template="plotly_white")
            
            # Invertir eje Y si es Posición
            if metric == 'Pos':
                fig.update_yaxes(autorange="reversed")
            
            # Estilos personalizados para parecer "Tarjeta"
            card_color = '#ffffff' # Slate 800
            
            fig.update_traces(textposition="top center", 
                              textfont=dict(color="#f87171"), # Soft Red 
                              line=dict(color="#38bdf8", width=3), # Sky Blue
                              marker=dict(size=8, color="#38bdf8"))
            
            fig.update_layout(
                paper_bgcolor=card_color,
                plot_bgcolor=card_color,
                font=dict(color="#0f172a"),
                hovermode="x unified",
                title_font_size=18,
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="#e2e8f0")
            )
            return fig

        if selected_option == 'Todos':
            # Generate and offer combined image download
            img_bytes = generate_combined_chart_image_cached(team_data, selected_jornada, selected_team)
            if img_bytes:
                st.download_button(
                    label="📥 Descargar todos los cuadros en una única imagen",
                    data=img_bytes,
                    file_name=f"analisis_historico_completo_{selected_team}_J{selected_jornada}.png",
                    mime="image/png",
                    width="stretch"
                )
                
            def render_chart(metric_key, stretch=True):
                col_width = "stretch" if stretch else "content"
                cnf = {'toImageButtonOptions': {'format': 'png', 'filename': f'{selected_team}_{metric_map[metric_key]}_J{selected_jornada}'}}
                chart = create_chart(team_data, metric_key, f"Evolución de {metric_map[metric_key]} (Jornada {selected_jornada})")
                st.plotly_chart(chart, width=col_width, config=cnf)

            # Row 1: Position, Points
            c1, c2 = st.columns(2)
            with c1:
                render_chart('Pos')
            with c2:
                render_chart('PTS')

            # Row 2: Won, Drawn
            c3, c4 = st.columns(2)
            with c3:
                render_chart('PG')
            with c4:
                render_chart('PE')

            # Row 3: Lost, Empty
            c5, c6 = st.columns(2)
            with c5:
                render_chart('PP')
            with c6:
                st.empty() # Hueco vacio

            # Row 4: GF, GA
            c7, c8 = st.columns(2)
            with c7:
                render_chart('GF')
            with c8:
                render_chart('GC')

            # Row 5: Yellow, Red Cards
            c9, c10 = st.columns(2)
            with c9:
                render_chart('TA')
            with c10:
                render_chart('TR')
        else:
            # Gráfico único
            cnf = {'toImageButtonOptions': {'format': 'png', 'filename': f'{selected_team}_{metric_map[selected_option]}_J{selected_jornada}'}}
            fig = create_chart(team_data, selected_option, f"Evolución de {metric_map[selected_option]} - {selected_team} (Jornada {selected_jornada})")
            st.plotly_chart(fig, width="stretch", config=cnf)
            
    else:
        st.warning(f"No hay datos para {selected_team} en la Jornada {selected_jornada}.")

def render_twins_comparator(df_full):
    st.markdown("<h2><i class='bi bi-people'></i> Comparador de 'Gemelos' Históricos</h2>", unsafe_allow_html=True)
    st.markdown("Compara el rendimiento de una temporada específica de un equipo contra TODA la historia de la liga.")
    st.markdown("---")

    # --- Lógica de Selección de Jornada (Igual que en Análisis Histórico) ---
    last_season = df_full['Temporada'].max()
    max_jornada_global = df_full['Jornada'].max()
    
    if last_season:
        last_season_df = df_full[df_full['Temporada'] == last_season]
        default_jornada = int(last_season_df['Jornada'].max())
    else:
        default_jornada = int(max_jornada_global) if not pd.isna(max_jornada_global) else 38

    # Slider para seleccionar Jornada
    selected_jornada = st.slider("Comparar datos en la Jornada:", 1, int(max_jornada_global), value=default_jornada, key="comp_jornada_slider")
    
    # Filtrar DF por Jornada
    df = df_full[df_full['Jornada'] == selected_jornada].copy()
    
    equipos_unicos = sorted(df['Equipo'].unique())
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Selector de Equipo (Reutilizamos la lista pero permitimos selección independiente)
        comp_team = st.selectbox("Equipo Referencia:", equipos_unicos, key="comp_team")
        
    # Filtrar temporadas disponibles para ese equipo
    comp_team_seasons = df[df['Equipo'] == comp_team]['Temporada'].unique()
    
    with col2:
        comp_season = st.selectbox("Temporada Referencia:", sorted(comp_team_seasons, reverse=True), key="comp_season")
        
    # Obtener datos de referencia
    ref_data = df[(df['Equipo'] == comp_team) & (df['Temporada'] == comp_season)]
    
    if not ref_data.empty:
        ref_pos = ref_data.iloc[0]['Pos']
        ref_pts = ref_data.iloc[0]['PTS']
        
        # Tarjeta de estadisticas de referencia
        st.markdown(f"<div class='stAlert'><strong>REFERENCIA SELECCIONADA:</strong> {comp_team} ({comp_season})<br>"
                f"<i class='bi bi-trophy' style='color:#38bdf8'></i> Posición: <strong>{ref_pos}</strong> | <i class='bi bi-dribbble' style='color:#38bdf8'></i> Puntos: <strong>{ref_pts}</strong></div>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # ---------------------------------------------------------
        # Lógica de Comparación: PUNTOS (Closest Lower Match)
        # ---------------------------------------------------------
        
        points_comparison_results = []
        all_seasons = sorted(df['Temporada'].unique())
        
        for s in all_seasons:
            if s == comp_season:
                continue # Saltamos la temporada de referencia
                
            season_df = df[df['Temporada'] == s].copy()
            
            if season_df.empty:
                continue
                
            # 1. Buscar coincidencia exacta
            exact_match = season_df[season_df['PTS'] == ref_pts]
            
            if not exact_match.empty:
                for _, row in exact_match.iterrows():
                    points_comparison_results.append({
                        'Temporada': s,
                        'Equipo': row['Equipo'],
                        'Puntos': row['PTS'],
                        'Tipo': 'Exacto',
                        'Posición': row['Pos']
                    })
            else:
                # 2. Buscar aproximación por debajo (Closest Lower)
                # Filtramos equipos con puntos < ref_pts
                lower_matches = season_df[season_df['PTS'] < ref_pts]
                
                if not lower_matches.empty:
                    # Ordenamos por Puntos descendente para coger el mayor de los menores
                    lower_matches = lower_matches.sort_values(by='PTS', ascending=False)
                    closest_match = lower_matches.iloc[0]
                    
                    points_comparison_results.append({
                        'Temporada': s,
                        'Equipo': closest_match['Equipo'],
                        'Puntos': closest_match['PTS'],
                        'Tipo': 'Aproximado (Inf)',
                        'Posición': closest_match['Pos']
                    })
        
        df_pts_comp = pd.DataFrame(points_comparison_results)
        
        # ---------------------------------------------------------
        # Lógica de Comparación: POSICIÓN
        # ---------------------------------------------------------
        # Quién quedó en la posición 'ref_pos' en otras temporadas
        pos_comparison_results = []
        
        for s in all_seasons:
            if s == comp_season:
                continue
            
            season_df = df[df['Temporada'] == s]
            match_pos = season_df[season_df['Pos'] == ref_pos]
            
            for _, row in match_pos.iterrows():
                pos_comparison_results.append({
                    'Temporada': s,
                    'Equipo': row['Equipo'],
                    'Puntos': row['PTS']
                })
                
        df_pos_comp = pd.DataFrame(pos_comparison_results)

        # ---------------------------------------------------------
        # Visualización y Dashboards
        # ---------------------------------------------------------
        
        card_color = '#ffffff'

        card_color = '#ffffff'

        # Gráfico 1: Posición
        st.markdown(f"<h3><i class='bi bi-bar-chart-fill'></i> Equipos en Posición {ref_pos}</h3>", unsafe_allow_html=True)
        if not df_pos_comp.empty:
            # Ordenar cronológicamente
            df_pos_comp = df_pos_comp.sort_values(by='Temporada')
            
            # Formatear nombres para display vertical escalonado
            labels = []
            for i, team in enumerate(df_pos_comp['Equipo']):
                base = team.replace(' ', '<br>')
                labels.append(base + "<br><br><br>" if i % 2 == 1 else base)
            df_pos_comp['Equipo_Label'] = labels
            
            fig_pos = px.bar(df_pos_comp, x='Temporada', y='Puntos', color='Equipo',
                                hover_data=['Equipo', 'Puntos'],
                                text='Equipo_Label',
                                template="plotly_white")
                                
            fig_pos.update_traces(textposition='outside', cliponaxis=False)
            fig_pos.update_layout(
                showlegend=False,
                paper_bgcolor=card_color,
                plot_bgcolor=card_color,
                font=dict(color="#0f172a"),
                xaxis=dict(showgrid=False, categoryorder='category ascending'),
                yaxis=dict(showgrid=True, gridcolor="#e2e8f0"),
                margin=dict(t=100, b=40, l=40, r=40) # Margen superior amplio para etiquetas
            )
            st.plotly_chart(fig_pos, width="stretch")
        else:
            st.warning("No hay datos comparables para esta posición.")
        
        st.markdown("---")

        # Gráfico 2: Puntos
        st.markdown(f"<h3><i class='bi bi-bar-chart-fill'></i> Rendimiento similar a {ref_pts} Pts</h3>", unsafe_allow_html=True)
        if not df_pts_comp.empty:
            # Ordenar cronológicamente
            df_pts_comp = df_pts_comp.sort_values(by='Temporada')
            
            # Crear Gráfico de Puntos (Timeline de Equipos)
            # Eje Y: Equipos (Filas), Eje X: Temporadas
            # Esto evita solapamiento de nombres
            fig_pts = px.scatter(df_pts_comp, x='Temporada', y='Equipo',
                                color='Equipo', # Color distinto por equipo
                                text='Puntos', # Mostramos los puntos en el nodo
                                template="plotly_white",
                                hover_data=['Equipo', 'Puntos', 'Temporada'])

            # Estilo de los marcadores y texto
            fig_pts.update_traces(
                marker=dict(size=18, line=dict(width=2, color='#0f172a')), # Puntos grandes y visibles
                textposition='middle right', # Texto a la derecha del punto
                textfont=dict(size=14, family="Arial Black"),
                cliponaxis=False
            )
            
            # Hack para igualar color de texto con color de marcador
            for trace in fig_pts.data:
                try:
                    trace_color = trace.marker.color
                    # Aplicamos al texto (aunque plotly suele handlear esto bien en scatter, forzamos por si acaso)
                    trace.textfont.color = trace_color
                except:
                    pass
            
            # Calcular altura dinámica basada en número de equipos únicos (filas)
            unique_teams_count = df_pts_comp['Equipo'].nunique()
            dynamic_height = max(350, unique_teams_count * 60) + 100 # Min 350px, o 60px por equipo

            fig_pts.update_layout(
                showlegend=False, 
                paper_bgcolor=card_color,
                plot_bgcolor=card_color,
                font=dict(color="#0f172a"),
                
                # Eje X: Temporadas cronológicas
                xaxis=dict(
                    showgrid=True, 
                    gridcolor="#e2e8f0", 
                    title="Temporada",
                    type='category',
                    categoryorder='category ascending'
                ),
                
                # Eje Y: Equipos (Categorías)
                yaxis=dict(
                    showgrid=True, 
                    gridcolor="#334155", 
                    title="", # No hace falta titulo "Equipo" si ya son nombres
                    type='category',
                    # Ordenamos alfabéticamente al revés para que A empiece arriba si Plotly usa bottom-up, 
                    # o standar. Dejamos category ascending.
                    categoryorder='category ascending',
                    dtick=1 # Asegurar que se imprimen todos
                ),
                
                margin=dict(t=40, b=40, l=150, r=50), # Margen izquierdo amplio para los nombres de equipos
                height=dynamic_height
            )
            
            st.plotly_chart(fig_pts, width="stretch")
        else:
            st.warning("No hay datos comparables para estos puntos.")
            
        st.markdown("---")
        
        # ---------------------------------------------------------
        # Nueva Sección: PROYECCIÓN (Posición Final)
        # ---------------------------------------------------------
        st.markdown("<h2><i class='bi bi-eye'></i> Proyección: ¿Dónde acabaron estos equipos?</h2>", unsafe_allow_html=True)
        st.info("Estos gráficos muestran la **Posición Final** real que obtuvieron los equipos identificados arriba al terminar sus respectivas temporadas.")

        # Function Helper para buscar posición final
        def get_final_pos(row):
            season = row['Temporada']
            team = row['Equipo']
            # Filtrar df_full para esa temporada y equipo
            # Nota: df_full está disponible en el scope local de la función render_twins_comparator
            season_data = df_full[df_full['Temporada'] == season]
            team_data = season_data[season_data['Equipo'] == team]
            
            if not team_data.empty:
                # Obtener la última jornada registrada para ese equipo en esa temporada
                last_record = team_data.sort_values('Jornada', ascending=False).iloc[0]
                return last_record['Pos']
            return None

        # Helper para alternar posiciones de etiquetas
        def apply_alternating_labels(fig, df_source):
            # df_source debe tener una columna 'LabelPos' pre-calculada
            for trace in fig.data:
                team_name = trace.name
                # Filtrar filas para este equipo
                team_rows = df_source[df_source['Equipo'] == team_name]
                
                positions = []
                # Iterar sobre los puntos del trace (x=Temporada)
                # trace.x puede ser tuple, list o numpy array
                if trace.x is not None:
                    for x_val in trace.x:
                        # Buscar la posición asignada para esta Temporada y Equipo
                        # x_val es la Temporada
                        match = team_rows[team_rows['Temporada'] == x_val]
                        if not match.empty:
                            positions.append(match['LabelPos'].values[0])
                        else:
                            positions.append('top center') # Default
                    
                    trace.textposition = positions

        # --- Gráfico Proyección 1: Basado en Posición Inicial ---
        st.markdown(f"<h3><i class='bi bi-flag'></i> Final de los Equipos en Posición {ref_pos}</h3>", unsafe_allow_html=True)
        if not df_pos_comp.empty:
            # Calcular posiciones finales
            df_pos_comp['Posición Final'] = df_pos_comp.apply(get_final_pos, axis=1)
            
            # Ordenar y Calcular Posiciones de Etiquetas Alternas
            df_pos_comp = df_pos_comp.sort_values(by='Temporada')
            df_pos_comp['LabelPos'] = ['top center' if i % 2 == 0 else 'bottom center' for i in range(len(df_pos_comp))]
            
            # Crear Gráfico de Dispersión
            fig_final_pos = px.scatter(df_pos_comp, x='Temporada', y='Posición Final',
                                      color='Equipo',
                                      text='Equipo', # Mostrar Nombre del Equipo
                                      template="plotly_white",
                                      hover_data=['Equipo', 'Temporada', 'Posición Final'])
            
            fig_final_pos.update_traces(
                marker=dict(size=14, line=dict(width=1, color='#0f172a')),
                textfont=dict(size=12, color='#0f172a'),
                cliponaxis=False
            )
            
            # Aplicar alternancia de etiquetas
            apply_alternating_labels(fig_final_pos, df_pos_comp)
            
            fig_final_pos.update_layout(
                showlegend=False,
                paper_bgcolor=card_color,
                plot_bgcolor=card_color,
                font=dict(color="#0f172a"),
                xaxis=dict(showgrid=False, title="Temporada", categoryorder='category ascending'),
                yaxis=dict(showgrid=True, gridcolor="#e2e8f0", title="Posición Final", autorange="reversed", dtick=1), # Invertido para que 1º esté arriba
                margin=dict(t=40, b=40, l=40, r=40)
            )
            st.plotly_chart(fig_final_pos, width="stretch")
        else:
            st.warning("No hay datos para proyectar.")
        
        st.markdown("---") # Separador visual

        # --- Gráfico Proyección 2: Basado en Puntos Iniciales ---
        st.markdown(f"<h3><i class='bi bi-flag'></i> Final de los Equipos con {ref_pts} Pts</h3>", unsafe_allow_html=True)
        if not df_pts_comp.empty:
            # Calcular posiciones finales
            df_pts_comp['Posición Final'] = df_pts_comp.apply(get_final_pos, axis=1)
            
            # Ordenar y Calcular Posiciones de Etiquetas Alternas
            df_pts_comp = df_pts_comp.sort_values(by='Temporada')
            df_pts_comp['LabelPos'] = ['top center' if i % 2 == 0 else 'bottom center' for i in range(len(df_pts_comp))]
            
            # Crear Gráfico de Dispersión
            fig_final_pts = px.scatter(df_pts_comp, x='Temporada', y='Posición Final',
                                      color='Equipo',
                                      text='Equipo', # Mostrar Nombre del Equipo
                                      template="plotly_white",
                                      hover_data=['Equipo', 'Temporada', 'Posición Final'])
            
            fig_final_pts.update_traces(
                marker=dict(size=14, line=dict(width=1, color='#0f172a')),
                textfont=dict(size=12, color='#0f172a'),
                cliponaxis=False
            )
            
            # Aplicar alternancia de etiquetas
            apply_alternating_labels(fig_final_pts, df_pts_comp)
            
            fig_final_pts.update_layout(
                showlegend=False,
                paper_bgcolor=card_color,
                plot_bgcolor=card_color,
                font=dict(color="#0f172a"),
                xaxis=dict(showgrid=False, title="Temporada", categoryorder='category ascending'),
                yaxis=dict(showgrid=True, gridcolor="#e2e8f0", title="Posición Final", autorange="reversed", dtick=1),
                margin=dict(t=40, b=40, l=40, r=40)
            )
            st.plotly_chart(fig_final_pts, width="stretch")
        else:
            st.warning("No hay datos para proyectar.")
                
        st.markdown("---")
        
        # ---------------------------------------------------------
        # Nueva Sección: ZONA DE DESCENSO HISTÓRICA
        # ---------------------------------------------------------
        st.markdown("<h2><i class='bi bi-graph-down'></i> Zona de Descenso Histórica</h2>", unsafe_allow_html=True)
        st.info("Puntos con los que terminaron los 3 últimos clasificados de cada temporada (Evolución).")
        
        relegation_data = []
        for s in all_seasons:
            s_df = df_full[df_full['Temporada'] == s]
            if s_df.empty:
                continue
            
            # Obtener última jornada de esa temporada
            max_j = s_df['Jornada'].max()
            final_table = s_df[s_df['Jornada'] == max_j]
            
            # Ordenar por posición descendente (los últimos primero) y coger los 3 primeros
            bottom_3 = final_table.sort_values(by='Pos', ascending=False).head(3)
            
            labels = ["Último", "Penúltimo", "Antepenúltimo"]
            for i, (_, row) in enumerate(bottom_3.iterrows()):
                label = labels[i] if i < len(labels) else f"Descenso {i+1}"
                relegation_data.append({
                    'Temporada': s,
                    'Equipo': row['Equipo'],
                    'Puntos': row['PTS'],
                    'Posición': row['Pos'],
                    'Plaza': label
                })
        
        if relegation_data:
            df_relegation = pd.DataFrame(relegation_data)
            
            # Ordenar cronológicamente para el gráfico de líneas
            df_relegation = df_relegation.sort_values(by='Temporada')
            
            fig_rel = px.line(df_relegation, x='Temporada', y='Puntos', color='Plaza',
                              text='Equipo',
                              title='Evolución de Puntos en Zona de Descenso',
                              hover_data={'Equipo': True, 'Posición': True, 'Puntos': True, 'Temporada': False, 'Plaza': False},
                              template="plotly_white",
                              category_orders={"Plaza": ["Antepenúltimo", "Penúltimo", "Último"]}) # Orden en la leyenda
            
            fig_rel.update_traces(
                mode='lines+text',
                textposition='top center',
                textfont=dict(size=10, color='#0f172a'),
                line=dict(width=3)
            )
            
            fig_rel.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color="#0f172a"),
                hovermode="x unified",
                xaxis=dict(showgrid=False, title="Temporada", categoryorder='category ascending'),
                yaxis=dict(showgrid=True, gridcolor="#334155", title="Puntos", dtick=1, range=[10, 48]),
                margin=dict(t=50, b=40, l=40, r=40),
                legend_title_text='Posición de Descenso'
            )
            
            st.plotly_chart(fig_rel, width="stretch")
            
            # Datos opcionales en expander si se quiere visualizar
            with st.expander("Ver Datos de Referencia (Tablas Historicas)", icon=":material/table:"):
                st.write("Datos Base Reales")
                st.dataframe(df_relegation[['Temporada', 'Plaza', 'Equipo', 'Posición', 'Puntos']], hide_index=True, width="stretch")
                st.write("Datos de Proyección (Posición)")
                st.dataframe(df_pos_comp[['Temporada', 'Equipo', 'Posición Final']], width="stretch")
                st.write("Datos de Proyección (Puntos)")
                st.dataframe(df_pts_comp[['Temporada', 'Equipo', 'Posición Final']], width="stretch")

    else:
        st.error("Error obteniendo datos de referencia.")


def render_laliga_study_view(df):
    st.markdown("<h2><i class='bi bi-bar-chart-line'></i> Estudio LaLiga</h2>", unsafe_allow_html=True)
    st.markdown("Análisis detallado de rendimiento, virtudes y defectos de los equipos.")
    
    study_mode = st.radio("Modo de Estudio:", ["Estudio de Equipo", "Estudio Completo", "Comparativa 1ª vs 2ª Vuelta", "Progresión"], horizontal=True)
    st.markdown("---")
    
    # Pre-cálculo de medias de liga para comparaciones
    league_avgs = get_league_averages()
    
    if study_mode == "Estudio de Equipo":
        teams = get_teams_list()
        if not teams:
            st.error("No se encontraron carpetas de equipos en CSVs/Equipos.")
            return
            
        selected_team = st.selectbox("Selecciona un Equipo para Analizar:", sorted(teams))
        
        if selected_team:
            df_matches = load_team_match_stats(selected_team)
            if df_matches.empty:
                st.warning(f"No hay datos de resumen para {selected_team}.")
                return
            
            analysis = analyze_team_performance(selected_team, df_matches, league_avgs)
            
            if analysis:
                st.subheader(f"Análisis de {selected_team}")
                
                # Columnas de Virtudes y Defectos
                c1, c2 = st.columns(2)
                
                virtues = {k: v for k, v in analysis.items() if "Virtud" in v['Rating'] or "Bueno" in v['Rating']}
                problems = {k: v for k, v in analysis.items() if "Problema" in v['Rating'] or "Debilidad" in v['Rating']}
                
                with c1:
                    st.markdown("### <i class='bi bi-star'></i> Virtudes", unsafe_allow_html=True)
                    if virtues:
                        for k, v in virtues.items():
                            color = "green" if "Virtud" in v['Rating'] else "#90ee90"
                            st.markdown(f"- **{k}**: {v['Media']:.2f} ({v['Rating']})")
                    else:
                        st.info("Sin virtudes destacables sobre la media.")
                        
                with c2:
                    st.markdown("### <i class='bi bi-exclamation-triangle'></i> Problemas Detectados", unsafe_allow_html=True)
                    if problems:
                        for k, v in problems.items():
                            color = "red" if "Problema" in v['Rating'] else "#ffcccb"
                            st.markdown(f"- **{k}**: {v['Media']:.2f} ({v['Rating']})")
                    else:
                        st.success("Sin problemas críticos detectados.")
                        
                st.markdown("### <i class='bi bi-graph-up'></i> Estadísticas Detalladas", unsafe_allow_html=True)
                
                # Crear un DataFrame para mostrar bonito
                display_data = []
                for k, v in analysis.items():
                    display_data.append({
                        "Métrica": k,
                        "Media Promedio": f"{v['Media']:.2f}",
                        "Ultimos 5": f"{v['Recent']:.2f}",
                        "Tendencia": v['Tendencia'],
                        "Valoración Liga": v['Rating']
                    })
                
                st.dataframe(pd.DataFrame(display_data), width="stretch", hide_index=True)
                
                # Gráfico de Radar (Opcional, pero chulo)
                # Normalizar datos para radar sería ideal, por ahora omitimos para no complicar.
                
            else:
                st.error("No se pudo realizar el análisis.")
                
    elif study_mode == "Estudio Completo":
        st.markdown("<h3><i class='bi bi-globe'></i> Estudio Global de Equipos</h3>", unsafe_allow_html=True)
        st.info("Comparativa de rendimiento y valoraciones de todos los equipos disponibles.")
        
        teams = get_teams_list()
        all_team_data = []
        
        progress_bar = st.progress(0)
        
        for i, t in enumerate(teams):
            df_matches = load_team_match_stats(t)
            if not df_matches.empty:
                analysis = analyze_team_performance(t, df_matches, league_avgs)
                if analysis:
                    # Aplanamos para la tabla sumaria
                    row = {"Equipo": t}
                    # Seleccionamos algunas metricas clave
                    key_metrics = ['Goles', 'xG (Esperados)', 'Tiros', 'Tiros a Puerta']
                    
                    for k in key_metrics:
                        if k in analysis:
                            row[k] = analysis[k]['Media']
                            row[f"{k} Trend"] = analysis[k]['Tendencia']
                            
                    all_team_data.append(row)
            progress_bar.progress((i + 1) / len(teams))
            
        progress_bar.empty()
        
        if all_team_data:
            st.dataframe(pd.DataFrame(all_team_data), width="stretch")
        else:
            st.warning("No hay datos suficientes.")
            
    elif study_mode == "Comparativa 1ª vs 2ª Vuelta":
        st.markdown("<h3><i class='bi bi-arrow-left-right'></i> Comparativa de Temporadas: 1ª Vuelta vs 2ª Vuelta</h3>", unsafe_allow_html=True)
        st.info("Comparación de rendimiento entre la Jornada 19 (1ª Vuelta), la 2ª Vuelta (Diff) y el Final (J38).")
        
        # Obtener temporadas únicas ordenadas descendentemente
        seasons = sorted(df['Temporada'].unique(), reverse=True)
        
        # --- 1. PROCESAMIENTO PREVIO (Para botón global y visualización optimizada) ---
        processed_seasons = []
        
        for season in seasons:
            season_df = df[df['Temporada'] == season]
            
            # Determinar jornadas de corte
            if season == "2000-2001":
                header_half = "1ª Vuelta (J21)"
                header_final = "Final (J42)"
                header_2nd = "2ª Vuelta (J42 - J21)"
                j_half, j_final = 21, 42
            else:
                header_half = "1ª Vuelta (J19)"
                header_final = "Final (J38)"
                header_2nd = "2ª Vuelta (J38 - J19)"
                j_half, j_final = 19, 38
            
            # Obtener datos
            df_half = season_df[season_df['Jornada'] == j_half].copy()
            df_final = season_df[season_df['Jornada'] == j_final].copy()
            
            if df_half.empty or df_final.empty:
                continue
                
            # Preparar DF de Diferencias (2ª Vuelta)
            merged = pd.merge(df_half[['Equipo', 'PTS', 'GF', 'GC', 'PG', 'PE', 'PP', 'TA', 'TR']], 
                              df_final[['Equipo', 'PTS', 'GF', 'GC', 'PG', 'PE', 'PP', 'TA', 'TR']], 
                              on='Equipo', suffixes=('_half', '_final'))
            
            # Calcular diferencias
            merged['PTS'] = merged['PTS_final'] - merged['PTS_half']
            merged['GF']  = merged['GF_final'] - merged['GF_half']
            merged['GC']  = merged['GC_final'] - merged['GC_half']
            merged['PG']  = merged['PG_final'] - merged['PG_half']
            merged['PE']  = merged['PE_final'] - merged['PE_half']
            merged['PP']  = merged['PP_final'] - merged['PP_half']
            merged['TA']  = merged['TA_final'] - merged['TA_half']
            merged['TR']  = merged['TR_final'] - merged['TR_half']
            
            # DF 2ª Vuelta
            df_2nd = merged[['Equipo', 'PTS', 'GF', 'GC', 'PG', 'PE', 'PP', 'TA', 'TR']].copy()
            df_2nd = df_2nd.sort_values(by=['PTS', 'GF'], ascending=[False, False]).reset_index(drop=True)
            df_2nd.index += 1
            df_2nd['Pos'] = df_2nd.index # Crear columna Pos explícita para descarga/visualización
            
            # Ajustar columnas para visualización/descarga
            cols_export = ['Pos', 'Equipo', 'PTS', 'PG', 'PE', 'PP', 'GF', 'GC', 'TA', 'TR']
            
            # Asegurar que df_half y df_final tengan columnas limpias y ordenadas por Pos
            # NOTA: df_half y df_final ya vienen filtradas, pero 'Pos' es un int. Ordenamos por si acaso.
            df_half_clean = df_half[cols_export].sort_values('Pos')
            df_2nd_clean = df_2nd[cols_export]
            df_final_clean = df_final[cols_export].sort_values('Pos')
            
            processed_seasons.append({
                'season': season,
                'headers': (header_half, header_2nd, header_final),
                'dfs': (df_half_clean, df_2nd_clean, df_final_clean)
            })

        # Helper para escribir hoja side-by-side
        def write_season_sheet(writer, sheet_name, d1, d2, d3, h1, h2, h3):
            # Escribir Dataframes desplazados
            # Tabla 1: Col A (0)
            d1.to_excel(writer, sheet_name=sheet_name, startrow=1, startcol=0, index=False)
            
            # Tabla 2: Dejar 1 col en blanco. Start = len(d1) + 1
            c2 = len(d1.columns) + 1
            d2.to_excel(writer, sheet_name=sheet_name, startrow=1, startcol=c2, index=False)
            
            # Tabla 3: Dejar 1 col en blanco. Start = c2 + len(d2) + 1
            c3 = c2 + len(d2.columns) + 1
            d3.to_excel(writer, sheet_name=sheet_name, startrow=1, startcol=c3, index=False)
            
            # Escribir Headers Manualmente
            # Pandas Writer.sheets nos da acceso al worksheet xlsxwriter
            worksheet = writer.sheets[sheet_name]
            workbook = writer.book
            bold_fmt = workbook.add_format({'bold': True, 'align': 'center', 'font_size': 12})
            
            # Headers en fila 0
            # Fusionar celdas para el titulo de la tabla sería ideal, pero write simple vale
            # Calculamos centro aproximado o ponemos en la primera celda
            worksheet.write(0, 0, h1, bold_fmt)
            worksheet.write(0, c2, h2, bold_fmt)
            worksheet.write(0, c3, h3, bold_fmt)

        # --- 2. BOTÓN DE DESCARGA GLOBAL ---
        if processed_seasons:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                for item in processed_seasons:
                    # Hoja por temporada
                    write_season_sheet(
                        writer, 
                        item['season'], 
                        item['dfs'][0], item['dfs'][1], item['dfs'][2],
                        item['headers'][0], item['headers'][1], item['headers'][2]
                    )
            
            st.download_button(
                label="Descargar Histórico Completo (Excel)", icon=":material/download:",
                data=output.getvalue(),
                file_name="Comparativa_Historica_LaLiga.xlsx",
                mime="application/vnd.ms-excel"
            )
        
        # --- 3. RENDERIZADO VISUAL LOCAL ---
        for item in processed_seasons:
            season = item['season']
            h1, h2, h3 = item['headers']
            d1, d2, d3 = item['dfs']
            
            with st.expander(f"Temporada {season}", expanded=False):
                # Botón de Descarga Local
                output_local = io.BytesIO()
                with pd.ExcelWriter(output_local, engine='xlsxwriter') as writer:
                    # Hoja única "Datos"
                    write_season_sheet(writer, "Datos", d1, d2, d3, h1, h2, h3)
                    
                st.download_button(
                    label=f"Descargar Datos {season}", icon=":material/download:",
                    data=output_local.getvalue(),
                    file_name=f"Clasificacion_{season}.xlsx",
                    mime="application/vnd.ms-excel",
                    key=f"btn_{season}"
                )
                
                # Visualización
                col_config = {
                    "Pos": st.column_config.NumberColumn("Pos", format="%d"),
                    "PTS": st.column_config.NumberColumn("PTS", format="%d"),
                    "PG": st.column_config.NumberColumn("PG", format="%d"),
                    "PE": st.column_config.NumberColumn("PE", format="%d"),
                    "PP": st.column_config.NumberColumn("PP", format="%d"),
                    "TA": st.column_config.NumberColumn("TA", format="%d"),
                    "TR": st.column_config.NumberColumn("TR", format="%d")
                }
                
                # Vistas con Index seteado a Pos para display bonito
                v1 = d1.set_index('Pos')
                v2 = d2.set_index('Pos')
                v3 = d3.set_index('Pos')
                
                rows_max = max(len(v1), len(v2), len(v3))
                h_table = (rows_max + 1) * 35 + 3
                
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    st.markdown(f"#### {h1}")
                    st.dataframe(v1, column_config=col_config, width="stretch", height=h_table)
                    
                with c2:
                    st.markdown(f"#### {h2}")
                    st.dataframe(v2, column_config=col_config, width="stretch", height=h_table)
                    
                with c3:
                    st.markdown(f"#### {h3}")
                    st.dataframe(v3, column_config=col_config, width="stretch", height=h_table)

    elif study_mode == "Progresión":
        st.markdown("<h3><i class='bi bi-graph-up-arrow'></i> Progresión Histórica por Jornada</h3>", unsafe_allow_html=True)
        st.markdown(
            """
            Analiza la evolución de la posición de un equipo jornada a jornada en todas las temporadas disponibles.
            
            > **Notas Importantes:**
            > * Si un equipo no aparece en una temporada, es porque esa temporada había descendido (o no estaba en la categoría analizada).
            > * **EXCEPCIÓN 2000-2001**: Esta temporada contiene datos de **2ª División**. Por lo tanto, los equipos que **NO** aparecen en la temporada 2000-2001 es porque estaban en **1ª División**.
            """
        )
        
        # Filtramos solo equipos que existan en el DF global
        if df.empty:
             st.warning("No hay datos cargados.")
             return

        equipos_disponibles = sorted(df['Equipo'].unique())
        selected_team_prog = st.selectbox("Selecciona un Equipo:", equipos_disponibles)
        
        if selected_team_prog:
            # Obtener temporadas disponibles para este equipo
            available_seasons = sorted(df[df['Equipo'] == selected_team_prog]['Temporada'].unique(), reverse=True)
            
            # Selector de Temporadas (Multiselect)
            selected_seasons = st.multiselect("Selecciona Temporadas:", available_seasons, default=available_seasons)
            
            if selected_seasons:
                # Filtrar datos del equipo y temporadas
                prog_data = df[(df['Equipo'] == selected_team_prog) & (df['Temporada'].isin(selected_seasons))].copy()
                
                if not prog_data.empty:
                    # Ordenar cronológicamente
                    prog_data = prog_data.sort_values(by=['Temporada', 'Orden_Cronologico'])
                    
                    # Calcular tickvals/ticktext para mostrar el número real de jornada
                    all_ords = sorted(prog_data['Orden_Cronologico'].unique())
                    tick_map = {}
                    for _, rw in prog_data[['Orden_Cronologico', 'Jornada']].drop_duplicates().iterrows():
                        tick_map[rw['Orden_Cronologico']] = int(rw['Jornada'])
                    tickvals_prog = all_ords
                    ticktext_prog = [str(tick_map.get(o, o)) for o in all_ords]

                    # Crear Gráfico de Líneas Multi-Temporada
                    fig_prog = px.line(prog_data, x='Orden_Cronologico', y='Pos', color='Temporada',
                                       title=f"Progresión de {selected_team_prog} por Jornada",
                                       markers=True,
                                       hover_data={'Temporada': True, 'Jornada': True, 'Pos': True, 'PTS': True, 'PG': True, 'PE': True, 'PP': True, 'Orden_Cronologico': False},
                                       template="plotly_white")
                    
                    # Invertir eje Y (Posición 1 arriba)
                    fig_prog.update_yaxes(autorange="reversed", title="Posición", dtick=1, range=[21, 0])
                    fig_prog.update_xaxes(title="Jornada", tickmode='array', tickvals=tickvals_prog, ticktext=ticktext_prog)
                    
                    fig_prog.update_layout(
                        paper_bgcolor='#f0f2f5',
                        plot_bgcolor='#f0f2f5',
                        font=dict(color="#0f172a"),
                        legend_title_text='Temporada',
                        hovermode="x unified"
                    )
                    
                    st.plotly_chart(fig_prog, width="stretch")
                    
                    st.markdown("---")
                    
                    # --- NUEVA SECCIÓN: Comparativa de Puntos ---
                    st.markdown("<h3><i class='bi bi-bar-chart-line'></i> Comparativa de Puntos por Temporada</h3>", unsafe_allow_html=True)
                    st.info("Selecciona una temporada específica para comparar la progresión de puntos con otros equipos.")
                    
                    # 1. Selector de Temporada Única (para la comparativa)
                    season_for_comp = st.selectbox("Selecciona Temporada Base:", available_seasons, key="season_comp_prog")
                    
                    if season_for_comp:
                        # Datos de esa temporada completa
                        season_df = df[df['Temporada'] == season_for_comp]
                        teams_in_season = sorted(season_df['Equipo'].unique())
                        
                        # 2. Selector de Equipos a Comparar
                        # Por defecto pre-seleccionamos el equipo principal
                        default_teams = [selected_team_prog] if selected_team_prog in teams_in_season else []
                        
                        comp_teams = st.multiselect("Equipos a Comparar:", teams_in_season, default=default_teams, key="teams_comp_prog")
                        
                        if comp_teams:
                            # Filtrar datos
                            comp_data = season_df[season_df['Equipo'].isin(comp_teams)].copy()
                            
                            if not comp_data.empty:
                                comp_data = comp_data.sort_values(by=['Equipo', 'Orden_Cronologico'])
                                
                                # Calcular tickvals/ticktext para mostrar número real de jornada
                                ords_comp = sorted(comp_data['Orden_Cronologico'].unique())
                                tick_map_comp = {}
                                for _, rw in comp_data[['Orden_Cronologico', 'Jornada']].drop_duplicates().iterrows():
                                    tick_map_comp[rw['Orden_Cronologico']] = int(rw['Jornada'])
                                ticktext_comp = [str(tick_map_comp.get(o, o)) for o in ords_comp]

                                # Gráfico de Puntos
                                fig_pts = px.line(comp_data, x='Orden_Cronologico', y='PTS', color='Equipo',
                                                title=f"Progresión de Puntos - Temporada {season_for_comp}",
                                                markers=True,
                                                hover_data={'Equipo': True, 'Jornada': True, 'PTS': True, 'Pos': True, 'Orden_Cronologico': False},
                                                template="plotly_white")
                                
                                fig_pts.update_xaxes(title="Jornada", tickmode='array', tickvals=ords_comp, ticktext=ticktext_comp)
                                fig_pts.update_yaxes(title="Puntos Acumulados")
                                
                                fig_pts.update_layout(
                                    paper_bgcolor='#f0f2f5',
                                    plot_bgcolor='#f0f2f5',
                                    font=dict(color="#0f172a"),
                                    legend_title_text='Equipo',
                                    hovermode="x unified"
                                )
                                
                                st.plotly_chart(fig_pts, width="stretch")
                            else:
                                st.warning("No hay datos para los equipos seleccionados.")
                        else:
                            st.info("Selecciona al menos un equipo para comparar.")

                    else:
                        st.warning("No hay datos para las temporadas seleccionadas.")
                else:
                    st.warning("No hay datos para las temporadas seleccionadas.")
            else:
                st.info("Selecciona al menos una temporada para visualizar.")

        st.markdown("---")
        
        # ---------------------------------------------------------
        # NUEVA SECCIÓN: Comparativa Avanzada (Multi-Team / Multi-Season)
        # ---------------------------------------------------------
        st.markdown("<h3><i class='bi bi-search'></i> Comparativa Avanzada: Puntos y Posición</h3>", unsafe_allow_html=True)
        st.info("Construye tu propia comparativa añadiendo equipos de cualquier temporada.")

        # 1. Inicializar Estado de Sesión para guardar trazas
        if 'comparison_traces' not in st.session_state:
            st.session_state.comparison_traces = []

        # 2. Controles de Selección
        # Necesitamos todas las temporadas y equipos para dar libertad completa
        all_avail_seasons = sorted(df['Temporada'].unique(), reverse=True)
        
        c_add1, c_add2, c_add3 = st.columns([1, 2, 1])
        
        with c_add1:
            # Selector de Temporada
            # Usamos key única para no chocar con otros selectores
            sel_season_adv = st.selectbox("1. Temporada", all_avail_seasons, key="adv_season_sel")
            
        with c_add2:
            # Selector de Equipo (Filtrado por temporada seleccionada para UX limpia)
            teams_in_sel_season = sorted(df[df['Temporada'] == sel_season_adv]['Equipo'].unique())
            sel_team_adv = st.selectbox("2. Equipo", teams_in_sel_season, key="adv_team_sel")
            
        with c_add3:
            st.write("") # Spacer
            st.write("")
            if st.button("Añadir Comparativa", icon=":material/add:"):
                # Verificar si ya existe
                entry = {'Temporada': sel_season_adv, 'Equipo': sel_team_adv}
                if entry not in st.session_state.comparison_traces:
                    st.session_state.comparison_traces.append(entry)
                    st.success(f"Añadido: {sel_team_adv} ({sel_season_adv})")
                else:
                    st.warning("Esa combinación ya está en la lista.")

        # 3. Mostrar Seleccionados y Botón Limpiar
        if st.session_state.comparison_traces:
            st.write("### 📋 Selección Actual:")
            
            # Mostrar como chips o lista pequeña
            traces_text = [f"**{t['Equipo']}** ({t['Temporada']})" for t in st.session_state.comparison_traces]
            st.markdown(" | ".join(traces_text))
            
            if st.button("Limpiar Todo", icon=":material/delete:", type="secondary"):
                st.session_state.comparison_traces = []
                st.rerun()
                
            st.markdown("---")
            
            # 4. Procesar Datos y Graficar
            adv_data_list = []
            
            for trace in st.session_state.comparison_traces:
                t_season = trace['Temporada']
                t_team = trace['Equipo']
                
                # Fetch data
                trace_df = df[(df['Temporada'] == t_season) & (df['Equipo'] == t_team)].copy()
                
                if not trace_df.empty:
                    # Añadir columna Etiqueta para la leyenda
                    trace_df['Leyenda'] = f"{t_team} ({t_season})"
                    adv_data_list.append(trace_df)
            
            if adv_data_list:
                full_adv_df = pd.concat(adv_data_list)
                full_adv_df = full_adv_df.sort_values(by='Orden_Cronologico')

                # Calcular tickvals/ticktext para mostrar número real de jornada
                ords_adv = sorted(full_adv_df['Orden_Cronologico'].unique())
                tick_map_adv = {}
                for _, rw in full_adv_df[['Orden_Cronologico', 'Jornada']].drop_duplicates().iterrows():
                    tick_map_adv[rw['Orden_Cronologico']] = int(rw['Jornada'])
                ticktext_adv = [str(tick_map_adv.get(o, o)) for o in ords_adv]

                # --- GRÁFICO 3: PROGRESIÓN DE PUNTOS ---
                st.markdown("#### <i class='bi bi-dribbble'></i> Progresión de Puntos", unsafe_allow_html=True)
                fig_adv_pts = px.line(full_adv_df, x='Orden_Cronologico', y='PTS', color='Leyenda',
                                      title="Comparativa de Puntos Acumulados",
                                      markers=True,
                                      hover_data={'Equipo': True, 'Temporada': True, 'Jornada': True, 'PTS': True, 'Pos': True, 'Orden_Cronologico': False},
                                      template="plotly_white")
                
                fig_adv_pts.update_xaxes(title="Jornada", tickmode='array', tickvals=ords_adv, ticktext=ticktext_adv)
                fig_adv_pts.update_yaxes(title="Puntos")
                fig_adv_pts.update_layout(
                    paper_bgcolor='#f0f2f5',
                    plot_bgcolor='#f0f2f5',
                    font=dict(color="#0f172a"),
                    legend_title_text='Equipo (Temporada)',
                    hovermode="x unified"
                )
                st.plotly_chart(fig_adv_pts, width="stretch")
                
                st.write("") # Spacer

                # --- GRÁFICO 4: PROGRESIÓN DE POSICIÓN ---
                st.markdown("#### <i class='bi bi-graph-down-arrow'></i> Progresión de Posición", unsafe_allow_html=True)
                fig_adv_pos = px.line(full_adv_df, x='Orden_Cronologico', y='Pos', color='Leyenda',
                                      title="Comparativa de Posición en Liga",
                                      markers=True,
                                      hover_data={'Equipo': True, 'Temporada': True, 'Jornada': True, 'PTS': True, 'Pos': True, 'Orden_Cronologico': False},
                                      template="plotly_white")
                
                # Invertir eje Y para Posición
                fig_adv_pos.update_yaxes(autorange="reversed", title="Posición", dtick=1, range=[21, 0])
                fig_adv_pos.update_xaxes(title="Jornada", tickmode='array', tickvals=ords_adv, ticktext=ticktext_adv)
                fig_adv_pos.update_layout(
                    paper_bgcolor='#f0f2f5',
                    plot_bgcolor='#f0f2f5',
                    font=dict(color="#0f172a"),
                    legend_title_text='Equipo (Temporada)',
                    hovermode="x unified"
                )
                st.plotly_chart(fig_adv_pos, width="stretch")
                
            else:
                st.warning("No se encontraron datps para las selecciones realizadas.")
        
        else:
            st.info("Añade equipos arriba para comenzar la comparativa.", icon=":material/info:")

# --- Función: Progresión de Jugadores ---
def render_player_progression():
    st.markdown("<h2><i class='bi bi-person-lines-fill'></i> Progresión de Jugadores</h2>", unsafe_allow_html=True)
    st.markdown("Visualiza la evolución de las estadísticas de los jugadores a lo largo de las temporadas.")
    
    card_color = "#ffffff"

    # 1. Selección de Liga
    base_path = os.path.join("CSVs", "Ligas")
    if not os.path.exists(base_path):
        st.error(f"No se encontró el directorio de ligas: {base_path}")
        return

    ligas = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
    
    if not ligas:
        st.warning("No hay ligas disponibles.")
        return

    # Usar columnas para los selectores
    col1, col2 = st.columns(2)
    
    with col1:
        selected_liga = st.selectbox("Selecciona una Liga", ligas)

    # 2. Selección de Jugador
    players_path = os.path.join(base_path, selected_liga, "Jugadores")
    if not os.path.exists(players_path):
        st.warning(f"No hay carpeta de jugadores para la liga {selected_liga}")
        return

    # Listar archivos y extraer nombres de jugadores únicos
    # Formato buscado: [Nombre Jugador]_standard_dom_lg.csv
    files = glob.glob(os.path.join(players_path, "*_standard_dom_lg.csv"))
    
    player_names = set()
    for f in files:
        filename = os.path.basename(f)
        # Asumimos que el nombre es todo lo que hay antes de '_standard_dom_lg.csv'
        name_part = filename.replace("_standard_dom_lg.csv", "")
        player_names.add(name_part)

    sorted_players = sorted(list(player_names))

    with col2:
        selected_player = st.selectbox("Selecciona un Jugador", sorted_players) if sorted_players else None

    # Función auxiliar para cargar todos los jugadores (Cacheada)
    @st.cache_data
    def load_all_players_last_season():
        all_players_data = []
        # Buscar en todas las ligas
        root_ligas = os.path.join("CSVs", "Ligas")
        if not os.path.exists(root_ligas):
            return pd.DataFrame()

        # Recorrer Ligas
        for league in os.listdir(root_ligas):
            league_path = os.path.join(root_ligas, league, "Jugadores")
            if not os.path.isdir(league_path):
                continue
            
            # Buscar archivos standard
            player_files = glob.glob(os.path.join(league_path, "*_standard_dom_lg.csv"))
            
            for p_file in player_files:
                try:
                    p_df = pd.read_csv(p_file, sep=';', encoding='utf-8')
                    if not p_df.empty:
                        # Limpiar nombre
                        p_name = os.path.basename(p_file).replace("_standard_dom_lg.csv", "")
                        
                        # Coger última temporada
                        last_row = p_df.iloc[-1].copy()
                        last_row['PlayerName'] = p_name
                        last_row['League'] = league
                        all_players_data.append(last_row)
                except:
                    continue
        
        if all_players_data:
            return pd.DataFrame(all_players_data)
        return pd.DataFrame()

    if selected_player:
        # 3. Carga de Datos
        # Buscamos el archivo standard para ese jugador
        file_path = os.path.join(players_path, f"{selected_player}_standard_dom_lg.csv")
        
        if os.path.exists(file_path):
            try:
                # Leer CSV con delimitador ';'
                df = pd.read_csv(file_path, sep=';', encoding='utf-8')
                
                # Limpieza Básica
                numeric_cols = ['Min', 'Gls', 'Ast', 'G+A', 'xG', 'npxG', 'xC', 'PrgC', 'PrgP', '90s']
                # Intentamos convertir todo lo posible
                potential_metrics = [c for c in df.columns if c not in ['Season', 'Age', 'Squad', 'Country', 'Comp', 'LgRank', 'Matches', 'equipo actual']]
                
                for col in potential_metrics:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
                # 4. Visualización
                st.markdown(f"<h3><i class='bi bi-graph-up'></i> Evolución de {selected_player}</h3>", unsafe_allow_html=True)
                
                # Selector de Métricas
                default_metrics = ['Gls', 'Ast']
                default_metrics = [m for m in default_metrics if m in df.columns]
                
                selected_metrics = st.multiselect("Selecciona Métricas para Visualizar", potential_metrics, default=default_metrics)
                
                if selected_metrics:
                    # Crear el gráfico de líneas
                    fig = px.line(df, x='Season', y=selected_metrics, 
                                  markers=True,
                                  title=f"Estadísticas por Temporada: {selected_player}",
                                  hover_data=['Squad', 'Age', 'MP'],
                                  template="plotly_white")
                    
                    fig.update_layout(
                        paper_bgcolor=card_color,
                        plot_bgcolor=card_color,
                        font=dict(color="#0f172a"),
                        yaxis_title="Valor",
                        xaxis_title="Temporada",
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig, width="stretch")
                
                # Tabla de Datos
                with st.expander("Ver Datos Completos"):
                    st.dataframe(df)

                # --- 5. BUSCADOR DE JUGADORES SIMILARES ---
                st.markdown("---")
                st.markdown("<h3><i class='bi bi-people'></i> Buscar Jugadores Similares (Top 20)</h3>", unsafe_allow_html=True)
                
                # Definir métricas por defecto para la búsqueda simil
                # Preferiblemente métricas "Per 90" si existen, o normalizadas
                # Por ahora usaremos las Totales y calcularemos Per 90 al vuelo si '90s' existe
                sim_metrics_options = ['Gls', 'Ast', 'xG', 'npxG', 'xAG', 'PrgC', 'PrgP', 'Sh', 'SoT']
                # Filtrar solo las que existen en las columnas
                sim_metrics_options = [m for m in sim_metrics_options if m in df.columns]
                
                cols_sim = st.columns([3, 1])
                with cols_sim[0]:
                    selected_sim_metrics = st.multiselect("Métricas para Comparación", potential_metrics, default=sim_metrics_options)
                with cols_sim[1]:
                    st.write("") # Spacer
                    st.write("") 
                    btn_buscar = st.button("Buscar Gemelos", icon=":material/search:")

                if btn_buscar:
                    if not selected_sim_metrics:
                        st.warning("Selecciona al menos una métrica para comparar.")
                    else:
                        with st.spinner("Escaneando jugadores de todas las ligas..."):
                            df_all = load_all_players_last_season()
                            
                            if not df_all.empty:
                                import math

                                # Asegurar numéricos en la BD global
                                for col in selected_sim_metrics + ['90s']:
                                    if col in df_all.columns:
                                        df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
                                
                                # Datos de REFERENCIA (Última temporada del jugador seleccionado)
                                ref_row = df.iloc[-1]
                                
                                # Construir Vector Referencia (Normalizado por 90s si es posible)
                                # Si 90s > 0, dividimos. Si no, usamos valor absoluto.
                                ref_90s = ref_row.get('90s', 1)
                                if ref_90s <= 0: ref_90s = 1
                                
                                ref_vector = []
                                for m in selected_sim_metrics:
                                    val = ref_row.get(m, 0)
                                    # Simple normalización per 90 (opcional, usuario pidió 'similares')
                                    # Si comparamos totales (Goles) entre uno que jugó 3 partidos y otro 38, es injusto.
                                    # Usamos Per 90.
                                    ref_vector.append(val / ref_90s)
                                
                                # Calcular distancias
                                distances = []
                                
                                for idx, row in df_all.iterrows():
                                    # Ignorar al mismo jugador
                                    if row['PlayerName'] == selected_player:
                                        continue
                                        
                                    p_90s = row.get('90s', 1)
                                    if p_90s <= 0: p_90s = 1
                                    
                                    p_vector = []
                                    valid_player = True
                                    for m in selected_sim_metrics:
                                        if m not in row:
                                            valid_player = False
                                            break
                                        p_vals = row[m]
                                        p_vector.append(p_vals / p_90s)
                                    
                                    if valid_player:
                                        # Distancia Euclidiana (Manual con math)
                                        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(ref_vector, p_vector)))
                                        distances.append({
                                            'Jugador': row['PlayerName'],
                                            'Liga': row.get('League', 'Unknown'),
                                            'Edad': row.get('Age', 'Unknown'),
                                            'Equipo': row.get('Squad', 'Unknown'),
                                            'Similitud': dist, # Menor es mejor
                                            'Season': row.get('Season', 'Unknown')
                                        })
                                
                                # Crear DF de resultados
                                df_sim = pd.DataFrame(distances)
                                if not df_sim.empty:
                                    # Ordenar por menor distancia
                                    df_sim = df_sim.sort_values(by='Similitud', ascending=True).head(20)
                                    st.success(f"Top 20 Jugadores más similares a {selected_player} (Basado en {', '.join(selected_sim_metrics)})")
                                    st.dataframe(df_sim, width="stretch")
                                else:
                                    st.warning("No se encontraron coincidencias suficientes.")

                            else:
                                st.error("No se pudo cargar la base de datos de jugadores.")


            except Exception as e:
                st.error(f"Error al cargar datos del jugador: {e}")
        else:
            st.error(f"No se encontró el archivo de datos para {selected_player}")
    else:
        st.info("Selecciona un jugador para ver sus estadísticas.")

# --- Ejecución Principal ---


# Estilos CSS para simular el dashboard de la imagen (TEMA DARK BLUE)
st.markdown("""
<style>
    /* -------------------------------------------------------------------------
       MAIN THEME & COLORS
       ------------------------------------------------------------------------- */
       
    /* Sidebar Background - Dark */
    section[data-testid="stSidebar"] {
        background-color: #f0f2f5; /* Slate 800 */
        color: #0f172a;
        border-right: 1px solid #e2e8f0;
    }
    
    /* Main Background - Light */
    .stApp {
        background-color: #f8f9fa; /* Light Gray/White */
        color: #0f172a; /* Dark text for light background */
    }
    
    /* Global Text Color for Main App (override general text) */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp p, .stApp span, .stApp div, .stApp li {
        color: #0f172a;
    }
    /* Ensure Sidebar text remains light */
    section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4, section[data-testid="stSidebar"] h5, section[data-testid="stSidebar"] h6, section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] div, section[data-testid="stSidebar"] li {
        color: #0f172a !important;
    }
    
    /* -------------------------------------------------------------------------
       SIDEBAR SPECIFICS - PROFESSIONAL MENU
       ------------------------------------------------------------------------- */
    
    /* Sidebar Border - Subtle divider */
    section[data-testid="stSidebar"] {
        border-right: 1px solid #cbd5e1;
    }
    
    /* Hide the radio button circle itself */
    div.stRadio > div[role="radiogroup"] > label > div:first-child {
        display: none;
    }
    
    /* -------------------------------------------------------------------------
       CARDS & METRICS
       ------------------------------------------------------------------------- */
       
    /* Style Metrics as Cards in Light Mode */
    [data-testid="stMetric"] {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border: 1px solid #e2e8f0;
    }
    
    /* Metric Label */
    [data-testid="stMetricLabel"] {
        color: #64748b !important; /* Slate 500 */
        font-size: 0.9rem;
    }
    
    /* Metric Value */
    [data-testid="stMetricValue"] {
        color: #0ea5e9 !important; /* Light blue */
    }
    
    /* Info Box Styling (for compatibility) */
    [data-testid="stAlert"] {
        background-color: #ffffff;
        color: #0f172a;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 4px -1px rgba(0, 0, 0, 0.05);
    }
    
    /* Sidebar Expander styling (Header and Body) */
    section[data-testid="stSidebar"] div[data-testid="stExpander"] details summary {
        background-color: #e2e8f0 !important; /* Slate 700 (Lighter than #1e293b base) */
        color: #0f172a !important;
        border-radius: 4px;
    }
    section[data-testid="stSidebar"] div[data-testid="stExpander"] details summary:hover {
        background-color: #475569 !important; /* Lighter on hover */
    }
    section[data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        background-color: transparent !important;
        color: #0f172a !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stExpander"] {
        background-color: transparent !important;
        border: none !important;
    }
    
    /* Main window expander styling */
    .stApp div[data-testid="stExpander"] details summary {
        background-color: #e2e8f0 !important;
        color: #0f172a !important;
        border-radius: 4px;
    }
    
    /* -------------------------------------------------------------------------
       GENERAL COMPONENTS
       ------------------------------------------------------------------------- */
       
    /* Selectbox/Inputs in Main area */
    .stApp .stSelectbox div[data-baseweb="select"] > div {
        background-color: #ffffff;
        color: #0f172a;
        border-color: #cbd5e1;
    }
    .stApp .stSelectbox div[data-baseweb="popover"],
    .stApp div[data-baseweb="popover"] div {
         background-color: #ffffff;
         color: #0f172a;
    }
    
    /* Slider */
    .stSlider > div[data-baseweb="slider"] {
        /* Customizing slider colors works partly here, mostly defaults */
    }

</style>
""", unsafe_allow_html=True)

df = load_data()

# --- SIDEBAR MENU ---
# Inicializar estado de navegación
if 'active_section' not in st.session_state:
    st.session_state.active_section = 'Inicio'

def _set_section_estadisticas():
    st.session_state.active_section = st.session_state._radio_estadisticas

def _set_section_historico():
    st.session_state.active_section = f"Histórico: {st.session_state._radio_historico}"

with st.sidebar:
    st.title("⚽ Analytics Dashboard")
    st.markdown("---")
    
    with st.sidebar.expander("📊 Estadísticas", expanded=True):
        # Determinar índice actual
        _opts_est = ["Inicio", "Análisis Histórico", "Comparador Gemelos", "Estadísticas",
                     "Estudio Descensos", "Modelo Predictivo", "Árbitros", "Calendario", "Predicciones"]
        _cur_est = st.session_state.active_section if st.session_state.active_section in _opts_est else "Inicio"
        selection = st.radio(
            "Selecciona una vista:",
            _opts_est,
            index=_opts_est.index(_cur_est),
            key="_radio_estadisticas",
            on_change=_set_section_estadisticas,
            label_visibility="collapsed"
        )
        
    with st.sidebar.expander("📅 Histórico", expanded=st.session_state.active_section.startswith("Histórico:")):
        _is_pos_active = st.session_state.active_section == "Histórico: Posiciones"
        if st.button(
            "▶ Posiciones" if _is_pos_active else "Posiciones",
            key="btn_hist_posiciones",
            use_container_width=True,
            type="primary" if _is_pos_active else "secondary"
        ):
            st.session_state.active_section = "Histórico: Posiciones"
            st.rerun()


    with st.sidebar.expander("📥 Descargas", expanded=False):
        selection_downloads = st.radio(
            "Selecciona una opción:",
            ["Opción 1", "Opción 2"],
            label_visibility="collapsed"
        )
    
    st.markdown("---")
    st.caption("v1.2.0 | Desarrollado con Streamlit")

# --- MAIN CONTENT AREA ---


def render_statistics_section():
    st.markdown("<h2><i class='bi bi-graph-up'></i> Estadísticas de Competición</h2>", unsafe_allow_html=True)
    st.markdown("Explora lineups, mapas de tiro y estadísticas detalladas por temporada.")
        
    # 1. Selector de Vista (Movemos el estado arriba)
    if 'stats_view' not in st.session_state:
        st.session_state.stats_view = "lineups"
            
    # Botones de Acción
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Lineups", icon=":material/groups:", width="stretch", type="primary" if st.session_state.stats_view == "lineups" else "secondary"):
            st.session_state.stats_view = "lineups"
            st.rerun()
    with col2:
        if st.button("Shotmaps", icon=":material/my_location:", width="stretch", type="primary" if st.session_state.stats_view == "shotmaps" else "secondary"):
            st.session_state.stats_view = "shotmaps"
            st.rerun()
    with col3:
        if st.button("Statistics", icon=":material/bar_chart:", width="stretch", type="primary" if st.session_state.stats_view == "statistics" else "secondary"):
            st.session_state.stats_view = "statistics"
            st.rerun()
            
    current_view = st.session_state.stats_view
    st.subheader(f"Vista Actual: {current_view.capitalize()}")
    st.markdown("---")
    
    stats_root = os.path.join("CSVs", "Estadisticas")
    
    # La carpeta objetivo base es según la vista seleccionada (ej. CSVs/Estadisticas/lineups)
    view_root = os.path.join(stats_root, current_view)
    
    if not os.path.exists(view_root):
        st.warning(f"No se encontró el directorio para la vista: {view_root}")
        return

    # Listar subdirectorios (Temporadas) dentro de esa carpeta
    try:
        seasons = [d for d in os.listdir(view_root) if os.path.isdir(os.path.join(view_root, d))]
    except Exception as e:
        st.error(f"Error accediendo a directorio: {e}")
        return
    
    if not seasons:
        st.warning(f"No hay temporadas disponibles en {view_root}.")
        return
        
    col_season, _ = st.columns([1, 2])
    with col_season:
        selected_season = st.selectbox("Selecciona Temporada:", sorted(seasons, reverse=True))
    
    if not selected_season:
        return

    # 3. Lógica de Sub-módulos
    target_dir = os.path.join(view_root, selected_season)
    
    if not os.path.exists(target_dir):
        st.warning(f"No se encontró la carpeta '{current_view}' para la temporada {selected_season}.")
        return
        
    # Listar archivos CSV
    try:
        files = [f for f in os.listdir(target_dir) if f.endswith(".csv")]
    except Exception:
        files = []
    
    if not files:
        st.info(f"No hay archivos de {current_view} disponibles para esta temporada.")
        return
        
    # Selector de Archivo (Partido)
    selected_file = st.selectbox(f"Selecciona un archivo de {current_view}:", sorted(files))
    
    if selected_file:
        file_path = os.path.join(target_dir, selected_file)
        try:
            df = pd.read_csv(file_path)
            
            # --- Lógica Específica por Tipo ---
            if current_view == "lineups":
                st.dataframe(df, width="stretch")
                
            elif current_view == "shotmaps":
                # Mostrar tabla
                with st.expander("Ver Datos Completos", expanded=False):
                    st.dataframe(df, width="stretch")
                
                # Intento de gráfico si tiene columnas reconocibles
                # Buscamos columnas que contengan 'x', 'y' (case insensitive) pero exactas
                cols_lower = [c.lower() for c in df.columns]
                
                if 'x' in cols_lower and 'y' in cols_lower:
                     # Mapear nombres reales
                     col_x = df.columns[cols_lower.index('x')]
                     col_y = df.columns[cols_lower.index('y')]
                     col_player = df.columns[cols_lower.index('player')] if 'player' in cols_lower else None
                     
                     st.info("Visualización básica de tiros (X, Y)")
                     fig = px.scatter(df, x=col_x, y=col_y, 
                                      color=col_player,
                                      title="Mapa de Tiros",
                                      template="plotly_white")
                     
                     # Campo de fútbol básico (opcional, por ahora scatter simple)
                     fig.update_layout(
                        paper_bgcolor='#f0f2f5',
                        plot_bgcolor='green', # Simular campo
                        xaxis=dict(showgrid=False, visible=False),
                        yaxis=dict(showgrid=False, visible=False, scaleanchor="x", scaleratio=1),
                        height=600
                     )
                     st.plotly_chart(fig, width="stretch")
                else:
                    st.dataframe(df, width="stretch")
            
            elif current_view == "statistics":
                st.info("Cargando todas las estadísticas de la temporada para calcular agregados...")
                
                @st.cache_data
                def get_aggregated_stats(dir_path):
                    """Lee todos los archivos de stats y pre-calcula los agregados puros (sumas/medias)."""
                    all_files = [f for f in os.listdir(dir_path) if f.endswith("_statistics.csv")]
                    
                    df_list = []
                    unique_teams = set()
                    
                    for f in all_files:
                        try:
                            # Parse teams from name (e.g., Round 01_Home_Away_statistics.csv)
                            base = f.replace("_statistics.csv", "")
                            parts = base.split("_")
                            
                            home_team = "Local"
                            away_team = "Visitante"
                            
                            if len(parts) >= 3:
                                home_team = parts[1]
                                away_team = parts[2]
                                unique_teams.add(home_team)
                                unique_teams.add(away_team)
                            
                            temp_df = pd.read_csv(os.path.join(dir_path, f))
                            # Add contextual columns for filtering later
                            temp_df['HomeTeam'] = home_team
                            temp_df['AwayTeam'] = away_team
                            df_list.append(temp_df)
                        except Exception:
                            continue
                            
                    if not df_list:
                        return pd.DataFrame(), []
                        
                    full_df = pd.concat(df_list, ignore_index=True)
                    return full_df, sorted(list(unique_teams))
                
                # Fetch full data once
                stats_df_full, available_teams = get_aggregated_stats(target_dir)
                
                if stats_df_full.empty:
                    st.warning("No hay suficientes datos de estadísticas.")
                    return
                
                # UI Components
                col_team, col_mode = st.columns([1, 2])
                with col_team:
                    selected_stats_team = st.selectbox("Selecciona un Equipo (Estadísticas Agrupadas):", available_teams)
                
                with col_mode:
                    display_mode = st.radio("Filtro de Visualización:", 
                                            ["Estadísticas Totales", "Estadísticas como Local", "Estadísticas como Visitante"], 
                                            horizontal=True)
                
                if selected_stats_team:
                    # 1. Filtro Datos base el Rol Seleccionado
                    if display_mode == "Estadísticas Totales":
                        # Both Home and Away cases
                        cond_home = stats_df_full['HomeTeam'] == selected_stats_team
                        cond_away = stats_df_full['AwayTeam'] == selected_stats_team
                        filtered_df = stats_df_full[cond_home | cond_away].copy()
                        
                        # Extraer los datos relevantes a la columna del equipo
                        # Si era 'Home', el valor es 'Home'. Si era 'Away', el valor es 'Away'.
                        # Generemos una columna unificada 'TeamValue'
                        filtered_df['TeamValue'] = filtered_df.apply(
                            lambda row: row['Home'] if row['HomeTeam'] == selected_stats_team else row['Away'], 
                            axis=1
                        )
                        
                    elif display_mode == "Estadísticas como Local":
                        cond_home = stats_df_full['HomeTeam'] == selected_stats_team
                        filtered_df = stats_df_full[cond_home].copy()
                        filtered_df['TeamValue'] = filtered_df['Home']
                        
                    elif display_mode == "Estadísticas como Visitante":
                        cond_away = stats_df_full['AwayTeam'] == selected_stats_team
                        filtered_df = stats_df_full[cond_away].copy()
                        filtered_df['TeamValue'] = filtered_df['Away']
                    
                    # Grouping Key Columns (Period, Group, Name) based on Original CSV
                    key_cols = ['Period', 'Group', 'Name']
                    
                    if not filtered_df.empty and all(k in filtered_df.columns for k in key_cols):
                        # Ensure we convert TeamValue safely to operate on it
                        def agg_row(group):
                            name = group['Name'].iloc[0]
                            series = group['TeamValue']
                            
                            numeric_vals = []
                            pct_vals = []
                            
                            for val in series:
                                if pd.isna(val):
                                    continue
                                val = str(val).strip()
                                
                                # Check for percentages e.g. "46%"
                                if '%' in val:
                                    try:
                                        num = float(val.replace('%', ''))
                                        pct_vals.append(num)
                                    except:
                                        pass
                                else:
                                    # Basic numeric check
                                    match_float = re.match(r'^-?\d+(?:\.\d+)?$', val)
                                    if match_float:
                                        numeric_vals.append(float(val))
                            
                            # CÁLCULO ESPECÍFICO PARA GOLES ESPERADOS (xG)
                            if name == 'Expected goals':
                                if not numeric_vals:
                                    return "-"
                                n = len(numeric_vals)
                                suma = sum(numeric_vals) # Suma exacta sin redondeos intermedios
                                media = suma / n if n > 0 else 0
                                minimo = min(numeric_vals)
                                maximo = max(numeric_vals)
                                
                                return (
                                    f"Número de partidos analizados: {n}\n"
                                    f"Suma total de xG: {suma}\n"
                                    f"Media de xG por partido: {media:.2f}\n"
                                    f"Rango: {minimo} - {maximo}"
                                )
                            
                            # COMPORTAMIENTO POR DEFECTO PARA EL RESTO
                            if pct_vals:
                                return f"{sum(pct_vals) / len(pct_vals):.1f}%"
                            elif numeric_vals:
                                total = sum(numeric_vals)
                                return f"{int(total)}" if total.is_integer() else f"{total:.2f}"
                            else:
                                return "-"
                                
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter(action='ignore', category=FutureWarning)
                            aggregated = filtered_df.groupby(key_cols, sort=False).apply(agg_row).reset_index(name='Valor Agregado')
                        
                        # --- Traducción al Español ---
                        trans_dict = {
                            # Periods
                            'ALL': 'Todo el partido',
                            '1ST': '1ª Parte',
                            '2ND': '2ª Parte',
                            # Groups
                            'Match overview': 'Visión general',
                            'Shots': 'Tiros',
                            'Attack': 'Ataque',
                            'Passes': 'Pases',
                            'Duels': 'Duelos',
                            'Defending': 'Defensa',
                            'Goalkeeping': 'Portería',
                            # Names
                            'Ball possession': 'Posesión',
                            'Expected goals': 'Goles esperados (xG)',
                            'Big chances': 'Ocasiones claras',
                            'Total shots': 'Tiros totales',
                            'Goalkeeper saves': 'Paradas del portero',
                            'Corner kicks': 'Saques de esquina',
                            'Fouls': 'Faltas',
                            'Tackles': 'Entradas',
                            'Free kicks': 'Tiros libres',
                            'Yellow cards': 'Tarjetas amarillas',
                            'Red cards': 'Tarjetas rojas',
                            'Shots on target': 'Tiros a puerta',
                            'Hit woodwork': 'Al palo',
                            'Shots off target': 'Tiros fuera',
                            'Blocked shots': 'Tiros bloqueados',
                            'Shots inside box': 'Tiros dentro del área',
                            'Shots outside box': 'Tiros fuera del área',
                            'Big chances scored': 'Ocasiones claras marcadas',
                            'Big chances missed': 'Ocasiones claras falladas',
                            'Touches in penalty area': 'Toques en el área rival',
                            'Fouled in final third': 'Faltas recibidas en el último tercio',
                            'Offsides': 'Fueras de juego',
                            'Accurate passes': 'Pases precisos',
                            'Throw-ins': 'Saques de banda',
                            'Final third entries': 'Entradas al último tercio',
                            'Final third phase': 'Efectividad en el último tercio',
                            'Long balls': 'Balones largos',
                            'Crosses': 'Centros',
                            'Dispossessed': 'Pérdidas de balón',
                            'Ground duels': 'Duelos a ras de suelo',
                            'Aerial duels': 'Duelos aéreos',
                            'Dribbles': 'Regates',
                            'Tackles won': 'Entradas ganadas',
                            'Total tackles': 'Total de entradas',
                            'Interceptions': 'Intercepciones',
                            'Recoveries': 'Recuperaciones',
                            'Clearances': 'Despejes',
                            'Errors lead to a shot': 'Errores que resultan en tiro',
                            'Errors lead to a goal': 'Errores que resultan en gol',
                            'Total saves': 'Paradas totales',
                            'Goals prevented': 'Goles evitados',
                            'High claims': 'Salidas por alto',
                            'Goal kicks': 'Saques de puerta'
                        }
                        
                        aggregated['Period'] = aggregated['Period'].map(lambda x: trans_dict.get(x, x))
                        aggregated['Group'] = aggregated['Group'].map(lambda x: trans_dict.get(x, x))
                        aggregated['Name'] = aggregated['Name'].map(lambda x: trans_dict.get(x, x))
                        
                        aggregated.rename(columns={
                            'Period': 'Periodo',
                            'Group': 'Categoría',
                            'Name': 'Métrica'
                        }, inplace=True)
                        # -----------------------------
                        
                        st.subheader(f"Resultados Consolidados - {selected_stats_team} ({display_mode})")
                        st.dataframe(aggregated, width="stretch")
                    else:
                        st.warning(f"No match records found for {selected_stats_team} under '{display_mode}'.")

                    # --- NUEVA FUNCIONALIDAD: RATING DE JUGADORES POR JORNADA ---
                    st.markdown("---")
                    st.markdown("### <i class='bi bi-star-fill'></i> Rating de Jugadores por Jornada", unsafe_allow_html=True)
                    
                    # Interfaz de controles para esta sección específica
                    col_rtg_team, col_rtg_filter = st.columns(2)
                    with col_rtg_team:
                        selected_rtg_team = st.selectbox("Equipo a analizar:", available_teams, index=available_teams.index(selected_stats_team) if selected_stats_team in available_teams else 0, key="rtg_team")
                    with col_rtg_filter:
                        rtg_mode = st.radio("Filtro de Partidos:", ["Totales", "Partidos Como Local", "Partidos Como Visitante"], horizontal=True, key="rtg_mode")
                    lineups_dir = os.path.join(stats_root, "lineups", selected_season)
                    if os.path.exists(lineups_dir):
                        all_lineups = glob.glob(os.path.join(lineups_dir, "*.csv"))
                        
                        ratings_data = []
                        
                        for lf in all_lineups:
                            filename = os.path.basename(lf)
                            # Expected format: "Round XX_HomeTeam_AwayTeam_lineups.csv"
                            parts = filename.replace("_lineups.csv", "").split("_")
                            if len(parts) >= 3:
                                round_name = parts[0]
                                home_team = parts[1]
                                away_team = parts[2]
                                
                                # Verify if the selected team played this match based on filter
                                team_side = None
                                if rtg_mode == "Totales":
                                    if home_team == selected_rtg_team: team_side = "home"
                                    elif away_team == selected_rtg_team: team_side = "away"
                                elif rtg_mode == "Partidos Como Local":
                                    if home_team == selected_rtg_team: team_side = "home"
                                elif rtg_mode == "Partidos Como Visitante":
                                    if away_team == selected_rtg_team: team_side = "away"
                                    
                                if team_side:
                                    try:
                                        # Leemos el archivo y extraemos las ratings
                                        df_l = pd.read_csv(lf)
                                        # Filtramos por el equipo evaluado (home o away)
                                        df_team_l = df_l[df_l['Side'] == team_side]
                                        
                                        # Iterar sobre cada jugador del equipo en ese partido
                                        for _, row in df_team_l.iterrows():
                                            player_name = row.get('Name')
                                            rating = row.get('Rating')
                                            
                                            # Algunos no tienen rating (por ejemplo, entrenador, no jugaron, o NaN)
                                            if pd.notna(rating) and pd.notna(player_name):
                                                ratings_data.append({
                                                    'Jugador': str(player_name).strip(),
                                                    'Jornada': str(round_name).strip(),
                                                    'Rating': float(rating)
                                                })
                                    except Exception as e:
                                        print(f"Error procesando el archivo de lineups {lf}: {e}")
                                        pass
                        
                        if ratings_data:
                            # Convertimos a dataframe
                            df_ratings_raw = pd.DataFrame(ratings_data)
                            
                            # Intentamos ordenar las jornadas numéricamente si están en formato "Round XX"
                            def extract_round_num(r_str):
                                msgs = re.findall(r'\d+', r_str)
                                return int(msgs[0]) if msgs else 0
                                
                            unique_jornadas = sorted(df_ratings_raw['Jornada'].unique(), key=extract_round_num)
                            
                            # Pivotar la tabla: filas = Jugadores, columnas = Jornadas
                            df_ratings_pivot = df_ratings_raw.pivot_table(
                                index='Jugador', 
                                columns='Jornada', 
                                values='Rating', 
                                aggfunc='mean'  # Por si hubiera duplicados accidentales
                            )
                            
                            # Reordenar las columnas basándonos en el orden numérico de las jornadas
                            ordered_cols = [j for j in unique_jornadas if j in df_ratings_pivot.columns]
                            df_ratings_pivot = df_ratings_pivot[ordered_cols]
                            
                            # Calcular la media total del rating de cada jugador para ordenar
                            df_ratings_pivot['Media General'] = df_ratings_pivot.mean(axis=1)
                            df_ratings_pivot = df_ratings_pivot.sort_values(by='Media General', ascending=False)
                            
                            # Redondear y rellenar nulos
                            df_ratings_pivot = df_ratings_pivot.round(2)
                            
                            st.dataframe(df_ratings_pivot, width="stretch")
                        else:
                            st.info("No se encontraron ratings para este equipo con el filtro seleccionado.")
                    else:
                        st.warning("No se encontró la carpeta 'lineups' para esta temporada.")


        except Exception as e:
            st.error(f"Error leyendo el archivo: {e}")

# --- Helper Extractor Functions for Predictive Model ---
@st.cache_data
def get_referees_list():
    referees = set()
    target_dir = os.path.join("CSVs", "TemporadasPartidos")
    if os.path.exists(target_dir):
        for f in os.listdir(target_dir):
            if f.endswith(".csv"):
                try:
                    df = read_csv_dynamic(os.path.join(target_dir, f), sep=';')
                    if 'Arbitro' in df.columns:
                        refs = df['Arbitro'].dropna().unique()
                        for r in refs:
                            r_clean = str(r).strip()
                            if r_clean:
                                referees.add(r_clean)
                except:
                    pass
    return sorted(list(referees))

@st.cache_data
def get_referee_stats(ref_name):
    target_dir = os.path.join("CSVs", "TemporadasPartidos")
    matches = 0
    home_wins = 0
    away_wins = 0
    draws = 0
    total_gl = 0
    total_gv = 0
    
    if os.path.exists(target_dir):
        for f in os.listdir(target_dir):
            if f.endswith(".csv"):
                try:
                    df = read_csv_dynamic(os.path.join(target_dir, f), sep=';')
                    if 'Arbitro' in df.columns:
                        df_ref = df[df['Arbitro'].astype(str).str.strip() == ref_name].copy()
                        for _, row in df_ref.iterrows():
                            gl, gv = row.get('GL', 0), row.get('GV', 0)
                            try:
                                gl = int(gl)
                                gv = int(gv)
                            except:
                                continue
                            matches += 1
                            total_gl += gl
                            total_gv += gv
                            if gl > gv:
                                home_wins += 1
                            elif gv > gl:
                                away_wins += 1
                            else:
                                draws += 1
                except:
                    pass
    if matches == 0:
         return {"partidos": 0}
    return {
        "partidos": matches,
        "perc_local": round((home_wins/matches)*100, 1),
        "perc_visitante": round((away_wins/matches)*100, 1),
        "perc_empate": round((draws/matches)*100, 1),
        "media_goles": round((total_gl+total_gv)/matches, 2)
    }

@st.cache_data
def get_h2h_matches(team_a, team_b):
    target_dir = os.path.join("CSVs", "TemporadasPartidos")
    h2h_results = []
    if os.path.exists(target_dir):
        files = sorted([f for f in os.listdir(target_dir) if f.endswith(".csv")], reverse=True)
        for f in files:
            try:
                df = read_csv_dynamic(os.path.join(target_dir, f), sep=';')
                season = f.replace(".csv","")
                df_ab = df[((df['Local'] == team_a) & (df['Visitante'] == team_b)) | 
                           ((df['Local'] == team_b) & (df['Visitante'] == team_a))]
                for _, row in df_ab.iterrows():
                    h2h_results.append(f"{season}: {row['Local']} {row.get('GL','-')} - {row.get('GV','-')} {row['Visitante']}")
            except:
                pass
    return h2h_results[:5] # Last 5 matches

@st.cache_data
def get_historical_standings(team_name):
    # Search all standings to find average pos and points
    search_path = os.path.join("CSVs", "TemporadasClasificaciones", "Temporadas Clasificaciones.xlsx - [*.csv")
    all_files = glob.glob(search_path)
    if not all_files:
        target_dir = os.path.join("CSVs", "TemporadasClasificaciones")
        if os.path.exists(target_dir):
            all_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.startswith("Temporadas Clasificaciones.xlsx - [") and f.endswith("].csv")]
            
    pos_history = []
    pts_history = []
    for f in all_files:
        try:
            df = pd.read_csv(f, sep=";")
            # Find the final position (max jornada or last entry for the team)
            df_team = df[df['Equipo'] == team_name]
            if not df_team.empty:
                last_row = df_team.iloc[-1]
                pos_history.append(pd.to_numeric(last_row['Pos'], errors='coerce'))
                pts_history.append(pd.to_numeric(last_row['PTS'], errors='coerce'))
        except:
            pass
            
    pos_history = [p for p in pos_history if pd.notna(p)]
    pts_history = [p for p in pts_history if pd.notna(p)]
    
    if not pos_history: return None
    return {
        "media_pos": round(sum(pos_history) / len(pos_history), 1),
        "media_pts": round(sum(pts_history) / len(pts_history), 1),
        "temporadas": len(pos_history)
    }

@st.cache_data
def get_top_players(season, team_name):
    target_dir = os.path.join("CSVs", "Estadisticas", season, "lineups")
    players_rating = {}
    if os.path.exists(target_dir):
        all_files = [f for f in os.listdir(target_dir) if team_name in f and f.endswith("_lineups.csv")]
        for f in all_files:
            try:
                df = pd.read_csv(os.path.join(target_dir, f))
                # Identify if team is home or away based on filename to filter IsHome or Side
                parts = f.replace("_lineups.csv", "").split("_")
                home = parts[1]
                side = "home" if home == team_name else "away"
                
                df_side = df[df['Side'] == side]
                for _, row in df_side.iterrows():
                    name = str(row['Name'])
                    rating = pd.to_numeric(row['Rating'], errors='coerce')
                    if pd.notna(rating):
                        if name not in players_rating:
                            players_rating[name] = []
                        players_rating[name].append(rating)
            except:
                pass
                
    avg_ratings = []
    for p, rats in players_rating.items():
        if len(rats) >= 3: # min 3 matches
            avg_ratings.append((p, sum(rats)/len(rats)))
            
    avg_ratings.sort(key=lambda x: x[1], reverse=True)
    return [f"{p} ({round(r, 2)})" for p, r in avg_ratings[:3]]

@st.cache_data
def get_shooting_profile(season, team_name):
    target_dir = os.path.join("CSVs", "Estadisticas", season, "shotmaps")
    profile = {"situations": {}, "body_parts": {}}
    if os.path.exists(target_dir):
        all_files = [f for f in os.listdir(target_dir) if team_name in f and f.endswith("_shotmap.csv")]
        for f in all_files:
            try:
                df = pd.read_csv(os.path.join(target_dir, f))
                
                parts = f.replace("_shotmap.csv", "").split("_")
                home = parts[1]
                is_home = True if home == team_name else False
                
                df_side = df[df['IsHome'] == is_home]
                
                for _, row in df_side.iterrows():
                    sit = str(row.get('Situation', ''))
                    body = str(row.get('BodyPart', ''))
                    if sit and sit != 'nan':
                        profile["situations"][sit] = profile["situations"].get(sit, 0) + 1
                    if body and body != 'nan':
                        profile["body_parts"][body] = profile["body_parts"].get(body, 0) + 1
            except:
                pass
    
    # Sort and format
    sits = sorted(profile["situations"].items(), key=lambda x: x[1], reverse=True)
    bodies = sorted(profile["body_parts"].items(), key=lambda x: x[1], reverse=True)
    
    sit_str = ", ".join([f"{k} ({v})" for k,v in sits[:2]]) if sits else "No info"
    bod_str = ", ".join([f"{k} ({v})" for k,v in bodies[:2]]) if bodies else "No info"
    
    return sit_str, bod_str

def render_predictive_model():
    st.markdown("<h2><i class='bi bi-cpu'></i> Modelo Predictivo (Sport Analytics)</h2>", unsafe_allow_html=True)
    st.markdown("Genera una **Simulación de Probabilidad Multivariante** para un partido inminente basándote en el rendimiento histórico acumulado de ambos equipos.")
    stats_root = os.path.join("CSVs", "Estadisticas", "statistics")
    if not os.path.exists(stats_root):
        st.error(f"No se encontró el directorio de estadísticas predictivas: {stats_root}")
        return

    try:
        seasons = [d for d in os.listdir(stats_root) if os.path.isdir(os.path.join(stats_root, d))]
    except Exception as e:
        st.error(f"Error accediendo a directorio de estadísticas predictivas: {e}")
        return
    
    if not seasons:
        st.warning(f"No hay temporadas disponibles en {stats_root}.")
        return
        
    col_season, _ = st.columns([1, 2])
    with col_season:
        selected_season = st.selectbox("Selecciona Temporada:", sorted(seasons, reverse=True), key="pred_season_sel")
        
    st.markdown("---")
    
    target_dir = os.path.join(stats_root, selected_season)
    if not os.path.exists(target_dir):
        st.warning(f"No hay datos de 'statistics' para la temporada {selected_season}.")
        return

    @st.cache_data
    def get_predictive_stats(dir_path):
        all_files = [f for f in os.listdir(dir_path) if f.endswith("_statistics.csv")]
        df_list = []
        unique_teams = set()
        
        for f in all_files:
            try:
                base = f.replace("_statistics.csv", "")
                parts = base.split("_")
                home_team = "Local"
                away_team = "Visitante"
                if len(parts) >= 3:
                    home_team = parts[1]
                    away_team = parts[2]
                    unique_teams.add(home_team)
                    unique_teams.add(away_team)
                
                temp_df = pd.read_csv(os.path.join(dir_path, f))
                temp_df['HomeTeam'] = home_team
                temp_df['AwayTeam'] = away_team
                df_list.append(temp_df)
            except Exception:
                continue
                
        if not df_list:
            return pd.DataFrame(), []
            
        return pd.concat(df_list, ignore_index=True), sorted(list(unique_teams))

    full_stats_df, available_teams = get_predictive_stats(target_dir)
    
    if full_stats_df.empty:
        st.warning("No hay datos estadísticos para generar el modelo.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        local_team = st.selectbox("Equipo Local:", available_teams, key="pred_local")
    with col2:
        away_team = st.selectbox("Equipo Visitante:", available_teams, key="pred_away")
    with col3:
        all_refs = get_referees_list()
        selected_ref = st.selectbox("Árbitro del Encuentro (Opcional):", ["Ninguno"] + all_refs, key="pred_ref")

    if local_team and away_team:
        if local_team == away_team:
            st.warning("Selecciona dos equipos diferentes.")
            return
            
        # Filtros: Rendimiento Local en Casa, Rendimiento Visitante Fuera
        df_local = full_stats_df[full_stats_df['HomeTeam'] == local_team].copy()
        df_away = full_stats_df[full_stats_df['AwayTeam'] == away_team].copy()
        
        def extract_metrics_mean(df, value_col):
            """Calculates the mean for key numerical metrics ignoring non-numbers."""
            means = {}
            for name, group in df.groupby('Name'):
                series = group[value_col].astype(str).str.replace('%', '').str.strip()
                # Convert to numeric, coercing errors to NaN
                numeric_series = pd.to_numeric(series, errors='coerce')
                mean_val = numeric_series.mean()
                if pd.notna(mean_val):
                    means[name] = round(mean_val, 2)
                else:
                    means[name] = 0.0
            return means

        local_means = extract_metrics_mean(df_local, 'Home')
        away_means = extract_metrics_mean(df_away, 'Away')
        
        # Mapeo Seguro de Métricas. Si no existe devuelven 0.0
        def safe_get(d, key): return round(d.get(key, 0.0), 2)
        
        local_data_str = f"""- Goles Esperados (xG): {safe_get(local_means, 'Expected goals')}
- Ocasiones Claras (Totales): {safe_get(local_means, 'Big chances')}
- Ocasiones Claras Anotadas: {safe_get(local_means, 'Big chances scored')}
- Goles Evitados: {safe_get(local_means, 'Goals prevented')}
- Paradas Totales: {safe_get(local_means, 'Total saves')}
- Toques en Área Rival: {safe_get(local_means, 'Touches in penalty area')}
- Entradas al Último Tercio: {safe_get(local_means, 'Final third entries')}
- Pases Precisos: {safe_get(local_means, 'Accurate passes')}
- Posesión (%): {safe_get(local_means, 'Ball possession')}
- Intercepciones: {safe_get(local_means, 'Interceptions')}
- Entradas Ganadas: {safe_get(local_means, 'Tackles won')}
- Errores Críticos (llevan a tiro/gol): {round(safe_get(local_means, 'Errors lead to a shot') + safe_get(local_means, 'Errors lead to a goal'), 2)}
- Pérdidas de Balón: {safe_get(local_means, 'Dispossessed')}
- Duelos Aéreos: {safe_get(local_means, 'Aerial duels')}
- Balones Largos: {safe_get(local_means, 'Long balls')}
- Centros: {safe_get(local_means, 'Crosses')}
- Despejes: {safe_get(local_means, 'Clearances')}
- Faltas Recibidas en Último Tercio: {safe_get(local_means, 'Fouled in final third')}
- Tarjetas Rojas: {safe_get(local_means, 'Red cards')}"""

        away_data_str = f"""- Goles Esperados (xG): {safe_get(away_means, 'Expected goals')}
- Ocasiones Claras (Totales): {safe_get(away_means, 'Big chances')}
- Ocasiones Claras Anotadas: {safe_get(away_means, 'Big chances scored')}
- Goles Evitados: {safe_get(away_means, 'Goals prevented')}
- Paradas Totales: {safe_get(away_means, 'Total saves')}
- Toques en Área Rival: {safe_get(away_means, 'Touches in penalty area')}
- Entradas al Último Tercio: {safe_get(away_means, 'Final third entries')}
- Pases Precisos: {safe_get(away_means, 'Accurate passes')}
- Posesión (%): {safe_get(away_means, 'Ball possession')}
- Intercepciones: {safe_get(away_means, 'Interceptions')}
- Entradas Ganadas: {safe_get(away_means, 'Tackles won')}
- Errores Críticos (llevan a tiro/gol): {round(safe_get(away_means, 'Errors lead to a shot') + safe_get(away_means, 'Errors lead to a goal'), 2)}
- Pérdidas de Balón: {safe_get(away_means, 'Dispossessed')}
- Duelos Aéreos: {safe_get(away_means, 'Aerial duels')}
- Balones Largos: {safe_get(away_means, 'Long balls')}
- Centros: {safe_get(away_means, 'Crosses')}
- Despejes: {safe_get(away_means, 'Clearances')}
- Faltas Recibidas en Último Tercio: {safe_get(away_means, 'Fouled in final third')}
- Tarjetas Rojas: {safe_get(away_means, 'Red cards')}"""

        # Extraer Contexto Adicional
        h2h = get_h2h_matches(local_team, away_team)
        h2h_str = "\n".join(h2h) if h2h else "No hay enfrentamientos recientes."

        ref_str = "No seleccionado/desconocido"
        if selected_ref != "Ninguno":
             ref_stats = get_referee_stats(selected_ref)
             ref_str = f"Árbitro: {selected_ref} | Partidos: {ref_stats.get('partidos',0)} | % Var: Loc {ref_stats.get('perc_local',0)}% - Vis {ref_stats.get('perc_visitante',0)}% | Goles/partido: {ref_stats.get('media_goles',0)}"

        local_hist = get_historical_standings(local_team)
        away_hist = get_historical_standings(away_team)
        hist_str = f"Local: Media Pos {local_hist['media_pos']} / Pts {local_hist['media_pts']} ({local_hist['temporadas']} temp.)\nVisitante: Media Pos {away_hist['media_pos']} / Pts {away_hist['media_pts']} ({away_hist['temporadas']} temp.)" if local_hist and away_hist else "No hay datos clasificatorios"

        local_players = get_top_players(selected_season, local_team)
        away_players = get_top_players(selected_season, away_team)
        
        local_sit, local_bod = get_shooting_profile(selected_season, local_team)
        away_sit, away_bod = get_shooting_profile(selected_season, away_team)

        # Construcción del Prompt Final (Para enviar al LLM)
        final_prompt = f"""### DATOS DEL PARTIDO A EVALUAR ###

**[CONVERGENCIA HISTÓRICA]**
H2H Reciente:
{h2h_str}
Estatus Histórico en Liga:
{hist_str}

**[EL ÁRBITRO INDICADO]**
{ref_str}

**[DATA_LOCAL] ({local_team} en casa)**
{local_data_str}
**Jugadores Activos Mejor Valorados:** {', '.join(local_players) if local_players else 'N/A'}
**Perfil de Tiro (Tendencia):** {local_sit} | {local_bod}

**[DATA_VISITANTE] ({away_team} fuera)**
{away_data_str}
**Jugadores Activos Mejor Valorados:** {', '.join(away_players) if away_players else 'N/A'}
**Perfil de Tiro (Tendencia):** {away_sit} | {away_bod}
"""

        # Visualización de los datos en la interfaz
        st.markdown("### <i class='bi bi-body-text'></i> DATOS DEL PARTIDO A EVALUAR", unsafe_allow_html=True)
        
        # Primero mostrar el contexto Global (Árbitro, H2H, Historial)
        with st.expander("Ver Contexto Global (Historial, Árbitro, H2H)", expanded=False):
            c_ctx1, c_ctx2 = st.columns(2)
            with c_ctx1:
                st.markdown(f"**Historial Clasificatorio:**\n{hist_str}")
                st.markdown(f"**Perfil de Árbitro:**\n{ref_str}")
            with c_ctx2:
                st.markdown(f"**Enfrentamientos H2H Recientes:**\n{h2h_str}")
                
        c_local, c_away = st.columns(2)
        
        with c_local:
            st.info(f"**[DATA_LOCAL] ({local_team} en casa)**\n\n**Jugadores Clave:** {', '.join(local_players) if local_players else 'N/A'}\n**Perfil de Tiro:** {local_sit} | {local_bod}\n\n{local_data_str}", icon="🏠")
            
        with c_away:
            st.info(f"**[DATA_VISITANTE] ({away_team} fuera)**\n\n**Jugadores Clave:** {', '.join(away_players) if away_players else 'N/A'}\n**Perfil de Tiro:** {away_sit} | {away_bod}\n\n{away_data_str}", icon="✈️")
        
        st.markdown("---")
        # Usamos la clave de nivel gratuito proporcionada, permitiendo sobreescribirla por entorno
        gemini_api_key = os.environ.get("GEMINI_API_KEY", "AIzaSyDOys1yt8mVLtka194e1W4aQPi69kXM4yE")
            
        if st.button("Ejecutar Simulación Predictiva", type="primary", width="stretch"):
            if not gemini_api_key:
                st.error("Por favor, introduce una API Key válida de Gemini (o configúrala en entorno).")
            else:
                system_prompt = """Actúa como un Científico de Datos Senior especializado en Modelado Predictivo de Fútbol. Tu objetivo es generar una **Simulación de Probabilidad Multivariante** para un partido inminente.
**Instrucciones del Modelo Analítico:**
1. **Cálculo de Eficiencia (Regresión):** No uses solo el xG. Ajusta la probabilidad de gol cruzando:
* `(Ocasiones claras marcadas / Ocasiones claras totales)` del atacante VS `(Goles evitados + Paradas totales)` del portero rival.
* `(Toques en área rival + Entradas al último tercio)` para determinar el **Índice de Dominio Territorial**.

2. **Ajuste de Flujo de Juego:** 
* Cruza `Pases precisos + Posesión` contra `Intercepciones + Entradas ganadas` del rival para predecir quién controlará el ritmo.
* Evalúa el riesgo de **"Error Crítico"** usando `Errores que resultan en tiro/gol` y `Pérdidas de balón`.

3. **Simulación de Poisson Ponderada:**
* Calcula el xG (Expectativa de Goles) para cada equipo, pero aplica un **coeficiente de corrección** basado en los `Duelos aéreos` y `Balones largos` si el equipo es directo, o pases precisos si es asociativo.

4. **Salida de Resultados (Formato Informe Técnico):**
* **Expectativa de Goles Ajustada (Adj_xG):** Local [Valor] vs Visitante [Valor].
* **Matriz de Probabilidad (1X2):** Local [%] | Empate [%] | Visitante [%].
* **Análisis de Correlación de Peligro:** Identifica la métrica "X" del local que más daño hará a la debilidad "Y" del visitante (ej: Centros vs Despejes deficientes).
* **Simulación de Escenarios:** 
  - % Probabilidad de "Clean Sheet" (Portería a cero).
  - % Probabilidad de Remontada (basado en `Faltas recibidas` y `Tarjetas rojas`).
* **Marcador Exacto de Máxima Probabilidad:** [Resultado] con [Intervalo de Confianza %].

**Restricción:** Ignora los nombres de los equipos si no los ves; céntrate exclusivamente en la correlación estadística de los números proporcionados. Aporta la matriz probabilística más exacta posible."""

                with st.spinner("🤖 Analizando datos con Gemini y ejecutando modelo predictivo multivariante..."):
                    try:
                        client = openai.OpenAI(
                            api_key=gemini_api_key,
                            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                        )
                        response = client.chat.completions.create(
                            model="gemini-2.5-flash",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": final_prompt}
                            ],
                            temperature=0.7
                        )
                        st.success("✅ Simulación Completada")
                        with st.expander("Resultados de la Simulación", expanded=True):
                            st.markdown(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"Error en la llamada a Gemini: {e}")

        st.markdown("""
        <div style="text-align: center; color: #475569; font-size: 0.9em; margin-top: 2rem;">
            Desarrollado para el análisis de rendimiento de equipos a lo largo de las temporadas.
        </div>
        """, unsafe_allow_html=True)

def render_referees_section():
    st.markdown("<h2><i class='bi bi-clipboard-data'></i> Análisis de Árbitros</h2>", unsafe_allow_html=True)
    st.markdown("Estudia el impacto estadístico por partido de los colegiados a partir del cruce de resultados y sumatorios de la clasificación.")

    with st.spinner("Cargando y cruzando bases de datos de partidos y clasificaciones..."):
        df_refs = load_referees_data()
        
    if df_refs.empty:
        st.warning("No se pudo cargar o cruzar datos de árbitros (esperando a que se generen o procesen los CSV).")
        return
        
    all_refs = sorted([r for r in df_refs['Arbitro'].unique() if str(r).strip() and str(r) != 'nan'])
    
    col_ref, col_team = st.columns(2)
    with col_ref:
        selected_ref = st.selectbox("1️⃣ Selecciona un Árbitro:", all_refs)
    
    df_ref = df_refs[df_refs['Arbitro'] == selected_ref].copy()
    
    ref_teams = sorted(df_ref['Equipo'].unique())
    
    with col_team:
        selected_team = st.selectbox("2️⃣ Equipo Específico (Opcional):", ["Todos"] + ref_teams)
        
    st.markdown("---")
    
    def render_metrics_row(df_sub, title):
        if df_sub.empty:
            st.info(f"No hay datos para {title}")
            return
            
        partidos = len(df_sub)
        ta_total = df_sub['TA_partido'].sum()
        tr_total = df_sub['TR_partido'].sum()
        gf_total = df_sub['GF_partido'].sum()
        gc_total = df_sub['GC_partido'].sum()
        
        ta_promedio = round(ta_total / partidos, 2)
        tr_promedio = round(tr_total / partidos, 2)
        
        st.markdown(f"#### {title} (Partidos: {partidos})")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tot. Amarillas al Equipo", int(ta_total), f"{ta_promedio}/partido")
        m2.metric("Tot. Rojas al Equipo", int(tr_total), f"{tr_promedio}/partido")
        m3.metric("Goles a Favor (Equipo)", int(gf_total))
        m4.metric("Goles en Contra (Equipo)", int(gc_total))
    
    if selected_team == "Todos":
        st.subheader(f"📊 Análisis Global: {selected_ref}")
        
        # Eliminar duplicados para contar partidos únicos (una fila por partido en lugar de dos)
        df_matches = df_ref.drop_duplicates(subset=['Temporada', 'Jornada', 'Local', 'Visitante'])
        partidos_totales = len(df_matches)
        
        ta_totales = df_ref['TA_partido'].sum()
        tr_totales = df_ref['TR_partido'].sum()
        
        st.markdown(f"#### Historial Completo ({partidos_totales} partidos)")
        m1, m2, m3 = st.columns(3)
        m1.metric("Amarillas por Partido (Media Total)", round(ta_totales/partidos_totales, 2) if partidos_totales > 0 else 0, f"Total Mostradas: {int(ta_totales)}")
        m2.metric("Rojas por Partido (Media Total)", round(tr_totales/partidos_totales, 2) if partidos_totales > 0 else 0, f"Total Mostradas: {int(tr_totales)}")
        m3.metric("Goles (Media Por Partido)", round(df_ref['GF_partido'].sum()/partidos_totales, 2) if partidos_totales > 0 else 0)
        
        st.markdown("#### Sesgo Local vs Visitante")
        st.markdown("¿Suele este árbitro amonestar más al equipo Local o al Visitante?")
        m1, m2, m3, m4 = st.columns(4)
        df_loc = df_ref[df_ref['Condicion'] == 'Local']
        df_vis = df_ref[df_ref['Condicion'] == 'Visitante']
        
        m1.metric("TA a Locales", int(df_loc['TA_partido'].sum()), f"{round(df_loc['TA_partido'].mean(), 2) if not df_loc.empty else 0}/p")
        m2.metric("TA a Visitantes", int(df_vis['TA_partido'].sum()), f"{round(df_vis['TA_partido'].mean(), 2) if not df_vis.empty else 0}/p")
        m3.metric("TR a Locales", int(df_loc['TR_partido'].sum()), f"{round(df_loc['TR_partido'].mean(), 2) if not df_loc.empty else 0}/p")
        m4.metric("TR a Visitantes", int(df_vis['TR_partido'].sum()), f"{round(df_vis['TR_partido'].mean(), 2) if not df_vis.empty else 0}/p")
        
        st.markdown("---")
        st.markdown("#### Estadísticas Detalladas por Equipo y Temporada")
        
        # Selector de temporada
        seasons = sorted(df_ref['Temporada'].unique(), reverse=True)
        selected_season = st.selectbox("Filtrar por Temporada:", ["Todas"] + seasons)
        
        # Filtrar datos de la tabla según temporada seleccionada
        if selected_season == "Todas":
            df_table = df_ref.copy()
        else:
            df_table = df_ref[df_ref['Temporada'] == selected_season].copy()
            
        if not df_table.empty:
            # Calcular PG, PE, PP para cada partido
            df_table['PG'] = (df_table['GF_partido'] > df_table['GC_partido']).astype(int)
            df_table['PE'] = (df_table['GF_partido'] == df_table['GC_partido']).astype(int)
            df_table['PP'] = (df_table['GF_partido'] < df_table['GC_partido']).astype(int)
            
            # Agrupar por equipo
            df_agrupado = df_table.groupby('Equipo').agg(
                Partidos=('Jornada', 'count'),
                PG=('PG', 'sum'),
                PE=('PE', 'sum'),
                PP=('PP', 'sum'),
                GF=('GF_partido', 'sum'),
                GC=('GC_partido', 'sum'),
                TA=('TA_partido', 'sum'),
                TR=('TR_partido', 'sum')
            ).reset_index()
            
            # Forzar tipos enteros
            cols_int = ['Partidos', 'PG', 'PE', 'PP', 'GF', 'GC', 'TA', 'TR']
            df_agrupado[cols_int] = df_agrupado[cols_int].astype(int)
            # Ocultamos el dataframe nativo y Plotly, y usamos HTML renderer
            # st.dataframe(df_agrupado, width="stretch", hide_index=True)
            
            # Identificamos el string de temporada a usar para los escudos
            if selected_season == "Todas":
                # Si es todas, usamos la ultima disponible en la BBDD general de este equipo
                # O la mas reciente general:
                season_for_img = df_ref['Temporada'].max()
            else:
                season_for_img = selected_season
                
            # Generamos filas HTML
            rows_html = ""
            for idx, row in df_agrupado.iterrows():
                team_name = row['Equipo']
                logo_b64 = get_img_b64(team_name, season_for_img)
                
                if logo_b64:
                    img_tag = f'<img src="data:image/png;base64,{logo_b64}" class="team-logo">'
                else:
                    img_tag = f'<span class="no-logo">{team_name[:3].upper()}</span>'
                    
                # Alternancia de colores para filas
                bg_color = "#f0f2f5" if idx % 2 == 0 else "#ffffff"
                    
                rows_html += f"""
                <tr style="background-color: {bg_color};">
                    <td class="team-cell">{img_tag} <span class="team-name">{team_name}</span></td>
                    <td>{row['Partidos']}</td>
                    <td class="win-text">{row['PG']}</td>
                    <td class="draw-text">{row['PE']}</td>
                    <td class="loss-text">{row['PP']}</td>
                    <td>{row['GF']}</td>
                    <td>{row['GC']}</td>
                    <td class="yellow-card">{row['TA']}</td>
                    <td class="red-card">{row['TR']}</td>
                </tr>
                """
                
            # --- 2. Generamos el listado de partidos ---
            df_matches = df_table.drop_duplicates(subset=['Temporada', 'Jornada', 'Local', 'Visitante']).copy()
            df_matches = df_matches.sort_values(by=['Temporada', 'Jornada'], ascending=[False, True])
            
            matches_html = ""
            for idx, row in df_matches.iterrows():
                # Alternancia basica para el listado
                bg_color = "#f0f2f5" if idx % 2 == 0 else "#ffffff"
                
                # Asegurar formato entero para los goles
                g_local = row.get('GL_x', row.get('GL', '-'))
                g_visitor = row.get('GV_x', row.get('GV', '-'))
                try: g_local = int(float(g_local))
                except: pass
                try: g_visitor = int(float(g_visitor))
                except: pass
                
                # Escudos
                logo_loc = get_img_b64(row['Local'], season_for_img)
                logo_vis = get_img_b64(row['Visitante'], season_for_img)
                
                img_loc_tag = f'<img src="data:image/png;base64,{logo_loc}" class="team-logo-small">' if logo_loc else f'<span class="no-logo-small">{row["Local"][:3].upper()}</span>'
                img_vis_tag = f'<img src="data:image/png;base64,{logo_vis}" class="team-logo-small">' if logo_vis else f'<span class="no-logo-small">{row["Visitante"][:3].upper()}</span>'
                    
                matches_html += f"""
                <tr style="background-color: {bg_color}; border-bottom: 1px solid #cbd5e1;">
                    <td style="padding: 10px; color: #475569;">{row['Temporada']}</td>
                    <td style="padding: 10px; color: #38bdf8;">Jornada {int(row['Jornada'])}</td>
                    <td style="padding: 10px; font-weight: 500; text-align: right;">{row['Local']} {img_loc_tag}</td>
                    <td style="padding: 10px; color: #64748b; width: 20px;">vs</td>
                    <td style="padding: 10px; font-weight: 500; text-align: left;">{img_vis_tag} {row['Visitante']}</td>
                    <td style="padding: 10px; font-weight: bold; color: #0f172a;">{g_local} - {g_visitor}</td>
                </tr>
                """
                
            # --- 3. Generamos la Tabla Fusionada ---
            merged_html = ""
            
            for idx, row in df_matches.iterrows():
                bg_color = "#f0f2f5" if idx % 2 == 0 else "#ffffff"
                
                loc_team = row['Local']
                vis_team = row['Visitante']
                
                # Obtener tarjetas especificas de este arbitro EN ESTE PARTIDO
                m_data = df_table[(df_table['Temporada'] == row['Temporada']) & 
                                  (df_table['Jornada'] == row['Jornada']) & 
                                  (df_table['Local'] == loc_team) & 
                                  (df_table['Visitante'] == vis_team)]
                                  
                loc_ta = int(m_data[m_data['Condicion'] == 'Local']['TA_partido'].sum())
                loc_tr = int(m_data[m_data['Condicion'] == 'Local']['TR_partido'].sum())
                vis_ta = int(m_data[m_data['Condicion'] == 'Visitante']['TA_partido'].sum())
                vis_tr = int(m_data[m_data['Condicion'] == 'Visitante']['TR_partido'].sum())
                
                # Escudos
                logo_loc = get_img_b64(loc_team, season_for_img)
                logo_vis = get_img_b64(vis_team, season_for_img)
                img_loc_tag = f'<img src="data:image/png;base64,{logo_loc}" class="team-logo-small">' if logo_loc else f'<span class="no-logo-small">{loc_team[:3].upper()}</span>'
                img_vis_tag = f'<img src="data:image/png;base64,{logo_vis}" class="team-logo-small">' if logo_vis else f'<span class="no-logo-small">{vis_team[:3].upper()}</span>'
                
                g_local = row.get('GL_x', row.get('GL', '-'))
                g_visitor = row.get('GV_x', row.get('GV', '-'))
                try: g_local = int(float(g_local))
                except: pass
                try: g_visitor = int(float(g_visitor))
                except: pass
                
                merged_html += f"""
                <tr style="background-color: {bg_color}; border-bottom: 1px solid #cbd5e1;">
                    <td style="padding: 8px; color: #475569;">{row['Temporada']}</td>
                    <td style="padding: 8px; color: #38bdf8;">Jornada {int(row['Jornada'])}</td>
                    <td style="padding: 8px; text-align: right;">{img_loc_tag}</td>
                    <td style="padding: 8px; font-weight: 500; text-align: right; border-right: 1px solid #475569;">
                        <span style="color:#facc15;">{loc_ta} TA</span> | <span style="color:#ef4444;">{loc_tr} TR</span>
                    </td>
                    <td style="padding: 8px; font-weight: bold; color: #0f172a; background-color: #ffffff;">{g_local} - {g_visitor}</td>
                    <td style="padding: 8px; font-weight: 500; text-align: left; border-left: 1px solid #475569;">
                         <span style="color:#facc15;">{vis_ta} TA</span> | <span style="color:#ef4444;">{vis_tr} TR</span>
                    </td>
                    <td style="padding: 8px; text-align: left;">{img_vis_tag}</td>
                </tr>
                """

            # Nombres para descarga
            ref_clean = selected_ref.replace(' ', '_')
            dl_file_1 = f"Stats_Global_{ref_clean}_{selected_season}.png"
            dl_file_2 = f"Partidos_{ref_clean}_{selected_season}.png"
            dl_file_3 = f"Fusion_{ref_clean}_{selected_season}.png"

            # Código HTML completo con CSS y html2canvas reparado en 3 bloques
            html_code = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
            <style>
                body {{
                    font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    background-color: transparent;
                    color: #0f172a;
                    margin: 0;
                    padding: 0;
                }}
                .section-container {{
                    margin-bottom: 40px;
                    display: flex;
                    flex-direction: column;
                    align-items: flex-end;
                    width: 100%;
                }}
                .download-btn {{
                    background-color: #38bdf8;
                    color: #0f172a;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 14px;
                    font-weight: 600;
                    cursor: pointer;
                    margin-bottom: 10px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    transition: background-color 0.2s;
                }}
                .download-btn:hover {{
                    background-color: #0ea5e9;
                }}
                .capture-wrapper {{
                    width: 100%;
                    background-color: #ffffff;
                    border-radius: 8px;
                    overflow: hidden;
                    padding: 0;
                    margin: 0;
                    border: 1px solid #cbd5e1;
                }}
                .table-title {{
                    background-color: #ffffff;
                    margin: 0;
                    padding: 15px 16px;
                    color: #38bdf8;
                    border-bottom: 2px solid #cbd5e1;
                    text-align: left;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    text-align: center;
                    font-size: 14px;
                }}
                th {{
                    background-color: #e2e8f0;
                    padding: 12px 8px;
                    font-weight: 600;
                    border-bottom: 2px solid #475569;
                    color: #0f172a;
                }}
                td {{
                    padding: 10px 8px;
                    border-bottom: 1px solid #cbd5e1;
                    color: #1e293b;
                }}
                .team-cell {{
                    text-align: left;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding-left: 16px;
                }}
                .team-logo {{ width: 28px; height: 28px; object-fit: contain; }}
                .team-logo-small {{ width: 22px; height: 22px; object-fit: contain; vertical-align: middle; margin: 0 5px; }}
                
                .no-logo {{
                    width: 28px; height: 28px; background-color: #e2e8f0; border-radius: 50%;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 10px; font-weight: bold; color: #475569;
                }}
                .no-logo-small {{
                    width: 22px; height: 22px; background-color: #e2e8f0; border-radius: 50%;
                    display: inline-flex; align-items: center; justify-content: center;
                    font-size: 8px; font-weight: bold; color: #475569; vertical-align: middle; margin: 0 5px;
                }}
                .team-name {{ font-weight: 500; }}
                .win-text {{ color: #4ade80; font-weight: bold; }}
                .draw-text {{ color: #475569; font-weight: bold; }}
                .loss-text {{ color: #f87171; font-weight: bold; }}
                .yellow-card {{ color: #facc15; font-weight: bold; }}
                .red-card {{ color: #ef4444; font-weight: bold; }}
            </style>
            </head>
            <body>
                <!-- TABLA 1: ESTADISTICAS GLOBALES -->
                <div class="section-container">
                    <button class="download-btn" onclick="descargarImagen('capture-1', '{dl_file_1}')">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M10.5 8.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0"/><path d="M2 4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-1.172a2 2 0 0 1-1.414-.586l-.828-.828A2 2 0 0 0 9.172 2H6.828a2 2 0 0 0-1.414.586l-.828.828A2 2 0 0 1 3.172 4zm.5 2a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1m9 2.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0"/></svg>
                        Descargar Totales
                    </button>
                    <div id="capture-1" class="capture-wrapper">
                        <h4 class="table-title">Estadísticas Totales por Equipo</h4>
                        <table>
                            <thead>
                                <tr>
                                    <th style="text-align: left; padding-left: 16px;">Equipo</th>
                                    <th>Partidos</th>
                                    <th>PG</th>
                                    <th>PE</th>
                                    <th>PP</th>
                                    <th>GF</th>
                                    <th>GC</th>
                                    <th>TA</th>
                                    <th>TR</th>
                                </tr>
                            </thead>
                            <tbody>{rows_html}</tbody>
                        </table>
                    </div>
                </div>

                <!-- TABLA 2: LISTADO DE PARTIDOS -->
                <div class="section-container">
                    <button class="download-btn" onclick="descargarImagen('capture-2', '{dl_file_2}')">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M10.5 8.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0"/><path d="M2 4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-1.172a2 2 0 0 1-1.414-.586l-.828-.828A2 2 0 0 0 9.172 2H6.828a2 2 0 0 0-1.414.586l-.828.828A2 2 0 0 1 3.172 4zm.5 2a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1m9 2.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0"/></svg>
                        Descargar Listado
                    </button>
                    <div id="capture-2" class="capture-wrapper">
                        <h4 class="table-title">Listado de Partidos Arbitrados ({len(df_matches)})</h4>
                        <table style="font-size: 13px;">
                            <tbody>{matches_html}</tbody>
                        </table>
                    </div>
                </div>

                <!-- TABLA 3: ESTADISTICAS FUSIONADAS -->
                <div class="section-container">
                    <button class="download-btn" onclick="descargarImagen('capture-3', '{dl_file_3}')">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M10.5 8.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0"/><path d="M2 4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-1.172a2 2 0 0 1-1.414-.586l-.828-.828A2 2 0 0 0 9.172 2H6.828a2 2 0 0 0-1.414.586l-.828.828A2 2 0 0 1 3.172 4zm.5 2a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1m9 2.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0"/></svg>
                        Descargar Fusión de Datos
                    </button>
                    <div id="capture-3" class="capture-wrapper">
                        <h4 class="table-title">Fusión: Resultado del Partido y Tarjetas del Árbitro en ese Encuentro</h4>
                        <table style="font-size: 13px;">
                            <thead>
                                <tr>
                                    <th>Temp</th>
                                    <th>Jor</th>
                                    <th style="text-align: right;">Local</th>
                                    <th style="text-align: right;">Tarjetas Loc.</th>
                                    <th>Score</th>
                                    <th style="text-align: left;">Tarjetas Vis.</th>
                                    <th style="text-align: left;">Visitante</th>
                                </tr>
                            </thead>
                            <tbody>{merged_html}</tbody>
                        </table>
                    </div>
                </div>

                <script>
                function descargarImagen(elementId, filename) {{
                    const captureDiv = document.getElementById(elementId);
                    
                    html2canvas(captureDiv, {{
                        backgroundColor: '#ffffff',
                        scale: 2, 
                        useCORS: true, 
                        logging: false
                    }}).then(canvas => {{
                        let link = document.createElement('a');
                        link.download = filename;
                        link.href = canvas.toDataURL("image/png");
                        link.click();
                    }});
                }}
                </script>
            </body>
            </html>
            """
            
            # Altura dinámica considerando 3 bloques separados
            t1_height = 100 + (len(df_agrupado) * 45) + 60
            t2_height = 100 + (len(df_matches) * 45) + 60
            t3_height = 100 + (len(df_matches) * 47) + 60 + 40 # cabecera extra en t3
            calc_height = t1_height + t2_height + t3_height + 150 # pads intra-secciones
            
            st.iframe(html_code, height=calc_height)
        else:
            st.info("No hay datos para la temporada seleccionada.")

    else:
        st.subheader(f"📊 Análisis: {selected_ref} arbitrando a {selected_team}")
        
        df_spec = df_ref[df_ref['Equipo'] == selected_team].copy()
        
        tab1, tab2, tab3 = st.tabs(["Global con este equipo", "Cuando es Local", "Cuando es Visitante"])
        
        with tab1:
            render_metrics_row(df_spec, "Rendimiento Total")
        with tab2:
            render_metrics_row(df_spec[df_spec['Condicion'] == 'Local'], "Rendimiento como Local")
        with tab3:
            render_metrics_row(df_spec[df_spec['Condicion'] == 'Visitante'], "Rendimiento como Visitante")

        st.markdown(f"#### 📅 Desglose de Partidos ({len(df_spec)} encontrados)")
        if not df_spec.empty:
            
            # Ordenar partidos cronologicamente
            df_display = df_spec.sort_values(by=['Temporada', 'Jornada'], ascending=[False, False])
            
            # Selector de temporada para este equipo
            spec_seasons = sorted(df_display['Temporada'].unique(), reverse=True)
            selected_spec_season = st.selectbox("Filtrar Temporada:", ["Todas"] + spec_seasons, key="spec_team_season")
            
            if selected_spec_season != "Todas":
                df_display = df_display[df_display['Temporada'] == selected_spec_season]
                season_for_img = selected_spec_season
            else:
                season_for_img = df_display['Temporada'].max()
                
            if df_display.empty:
                st.info("No hay partidos de este equipo con este árbitro en la temporada seleccionada.")
            else:
                matches_html = ""
                for idx, row in df_display.iterrows():
                    bg_color = "#f0f2f5" if len(matches_html.split("<tr>")) % 2 == 0 else "#ffffff"
                    
                    loc_team = row['Local']
                    vis_team = row['Visitante']
                    
                    # Escudos
                    logo_loc = get_img_b64(loc_team, season_for_img)
                    logo_vis = get_img_b64(vis_team, season_for_img)
                    img_loc_tag = f'<img src="data:image/png;base64,{logo_loc}" class="team-logo-small">' if logo_loc else f'<span class="no-logo-small">{loc_team[:3].upper()}</span>'
                    img_vis_tag = f'<img src="data:image/png;base64,{logo_vis}" class="team-logo-small">' if logo_vis else f'<span class="no-logo-small">{vis_team[:3].upper()}</span>'
                    
                    g_local = row.get('GL_x', row.get('GL', '-'))
                    g_visitor = row.get('GV_x', row.get('GV', '-'))
                    try: g_local = int(float(g_local))
                    except: pass
                    try: g_visitor = int(float(g_visitor))
                    except: pass
                    
                    ta_partido = int(row.get('TA_partido', 0))
                    tr_partido = int(row.get('TR_partido', 0))
                    
                    matches_html += f"""
                    <tr style="background-color: {bg_color}; border-bottom: 1px solid #cbd5e1;">
                        <td style="padding: 10px; color: #475569;">{row['Temporada']}</td>
                        <td style="padding: 10px; color: #38bdf8;">Jornada {int(row['Jornada'])}</td>
                        <td style="padding: 10px; font-weight: 500; text-align: right;">{loc_team} {img_loc_tag}</td>
                        <td style="padding: 10px; font-weight: bold; color: #0f172a;">{g_local} - {g_visitor}</td>
                        <td style="padding: 10px; font-weight: 500; text-align: left;">{img_vis_tag} {vis_team}</td>
                        <td style="padding: 10px; text-align: center; color: #334155;">{row['Arbitro']}</td>
                        <td style="padding: 10px; font-weight: bold; text-align: center; color: #facc15;">{ta_partido}</td>
                        <td style="padding: 10px; font-weight: bold; text-align: center; color: #ef4444;">{tr_partido}</td>
                    </tr>
                    """
                    
                dl_file_4 = f"Historial_Equipo_{selected_team.replace(' ', '_')}_{selected_ref.replace(' ', '_')}_{selected_spec_season}.png"

                html_code = f"""
                <!DOCTYPE html>
                <html>
                <head>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
                <style>
                    body {{ font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: transparent; color: #0f172a; margin: 0; padding: 0; }}
                    .section-container {{ display: flex; flex-direction: column; align-items: flex-end; width: 100%; }}
                    .download-btn {{ background-color: #38bdf8; color: #0f172a; border: none; border-radius: 6px; padding: 8px 16px; font-size: 14px; font-weight: 600; cursor: pointer; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; transition: background-color 0.2s; }}
                    .download-btn:hover {{ background-color: #0ea5e9; }}
                    .capture-wrapper {{ width: 100%; background-color: #ffffff; border-radius: 8px; overflow: hidden; padding: 0; margin: 0; border: 1px solid #cbd5e1; }}
                    .table-title {{ background-color: #ffffff; margin: 0; padding: 15px 16px; color: #38bdf8; border-bottom: 2px solid #cbd5e1; text-align: left; }}
                    table {{ width: 100%; border-collapse: collapse; text-align: center; font-size: 13px; }}
                    th {{ background-color: #e2e8f0; padding: 12px 8px; font-weight: 600; border-bottom: 2px solid #475569; color: #0f172a; }}
                    .team-logo-small {{ width: 22px; height: 22px; object-fit: contain; vertical-align: middle; margin: 0 5px; }}
                    .no-logo-small {{ width: 22px; height: 22px; background-color: #e2e8f0; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 8px; font-weight: bold; color: #475569; vertical-align: middle; margin: 0 5px; }}
                </style>
                </head>
                <body>
                    <div class="section-container">
                        <button class="download-btn" onclick="descargarImagen('capture-4', '{dl_file_4}')">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M10.5 8.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0"/><path d="M2 4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-1.172a2 2 0 0 1-1.414-.586l-.828-.828A2 2 0 0 0 9.172 2H6.828a2 2 0 0 0-1.414.586l-.828.828A2 2 0 0 1 3.172 4zm.5 2a.5.5 0 1 1 0-1 .5.5 0 0 1 0 1m9 2.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0"/></svg>
                            Descargar Historial del Equipo
                        </button>
                        <div id="capture-4" class="capture-wrapper">
                            <h4 class="table-title">Historial de Partidos: {selected_team} (Árbitro: {selected_ref}) - Temporada: {selected_spec_season} - {len(df_display)} Partidos</h4>
                            <table>
                                <thead>
                                    <tr>
                                        <th>Temporada</th>
                                        <th>Jornada</th>
                                        <th style="text-align: right;">Local</th>
                                        <th>Resultado</th>
                                        <th style="text-align: left;">Visitante</th>
                                        <th>Árbitro</th>
                                        <th>TA al Eq.</th>
                                        <th>TR al Eq.</th>
                                    </tr>
                                </thead>
                                <tbody>{matches_html}</tbody>
                            </table>
                        </div>
                    </div>

                    <script>
                    function descargarImagen(elementId, filename) {{
                        const captureDiv = document.getElementById(elementId);
                        html2canvas(captureDiv, {{
                            backgroundColor: '#ffffff',
                            scale: 2, 
                            useCORS: true, 
                            logging: false
                        }}).then(canvas => {{
                            let link = document.createElement('a');
                            link.download = filename;
                            link.href = canvas.toDataURL("image/png");
                            link.click();
                        }});
                    }}
                    </script>
                </body>
                </html>
                """
                calc_height = 100 + (len(df_display) * 45) + 60
                st.iframe(html_code, height=calc_height)

def get_team_image_filename(team_name):
    team_mapping = {
        "Deportivo Alavés": "alaves",
        "Alavés": "alaves",
        "Athletic Club": "athletic",
        "Athletic Club de Bilbao": "athletic",
        "Athletic de Bilbao": "athletic",
        "Atlético de Madrid": "atleticomadrid",
        "Atletico de Madrid": "atleticomadrid",
        "Atlético Madrid": "atleticomadrid",
        "Atletico Madrid": "atleticomadrid",
        "Celta de Vigo": "celta",
        "Celta Vigo": "celta",
        "Real Sociedad": "realsociedad",
        "Real Madrid": "realmadrid",
        "Rayo Vallecano": "rayovallecano",
        "Real Oviedo": "realoviedo",
        "Oviedo": "realoviedo",
        "Real Betis": "betis",
        "Betis": "betis",
        "Barcelona": "barcelona",
        "FC Barcelona": "barcelona",
        "Racing de Santander": "racingsantander",
        "Málaga": "malaga",
        "Malaga": "malaga",
        "Sevilla": "sevilla",
        "Sevilla FC": "sevilla",
        "Mallorca": "mallorca",
        "Valencia": "valencia",
        "Valladolid": "valladolid",
        "Espanyol": "espanyol",
        "Zaragoza": "zaragoza",
        "Levante": "levante",
        "Elche": "elche",
        "Albacete": "albacete",
        "Leganés": "leganes",
        "Leganes": "leganes",
        "Getafe": "getafe",
        "Sporting de Gijón": "sporting",
        "Sporting de Gijon": "sporting",
        "Córdoba": "cordoba",
        "Cordoba": "cordoba",
        "Eibar": "eibar",
        "Las Palmas": "udlaspalmas",
        "UD Las Palmas": "udlaspalmas",
        "Villarreal": "villarreal",
        "Osasuna": "osasuna",
        "Cádiz": "cadiz",
        "Cadiz": "cadiz",
        "Almería": "almeria",
        "Almeria": "almeria",
        "Granada": "granada",
        "Girona": "girona",
        "Huesca": "sdhuesca",
        "Deportivo de La Coruña": "deportivocoruna",
        "Deportivo de La Coruna": "deportivocoruna",
        "RC Deportivo": "deportivocoruna",
        "Burgos": "burgos",
        "Castellón": "castellon",
        "Castellon": "castellon",
        "Ceuta": "ceuta",
        "Andorra": "andorra",
        "Mirandés": "mirandes",
        "Mirandes": "mirandes",
        "Cultural Leonesa": "cultura_leonesa"
    }
    return team_mapping.get(str(team_name), str(team_name))
    
def get_img_b64(team_name, season):
    file_name = get_team_image_filename(team_name)
    path = os.path.join("Imagenes", "Escudos", "LigaEspanola", f"{file_name}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def render_calendar_view():
    st.markdown("<h2><i class='bi bi-calendar3'></i> Calendario de Partidos</h2>", unsafe_allow_html=True)
    st.markdown("Visualiza el calendario de partidos y resultados por equipo y temporada.")
    
    csv_dir = os.path.join("CSVs", "TemporadasPartidos")
    if not os.path.exists(csv_dir):
        st.error(f"No se encontró el directorio de partidos: {csv_dir}")
        return
        
    all_files = glob.glob(os.path.join(csv_dir, "*.csv"))
    if not all_files:
        st.warning("No hay archivos CSV en el directorio de temporadas.")
        return
        
    seasons = [os.path.basename(f).replace(".csv", "") for f in all_files]
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # 1. Selector de Temporada
        selected_season = st.selectbox("Selecciona Temporada", sorted(seasons, reverse=True))
        
    if not selected_season:
        return
        
    file_path = os.path.join(csv_dir, f"{selected_season}.csv")
    try:
        df_matches = read_csv_dynamic(file_path, sep=";")
    except Exception as e:
        st.error(f"Error al leer el archivo {file_path}: {e}")
        return
        
    # Verificar columnas básicas
    if 'Local' not in df_matches.columns or 'Visitante' not in df_matches.columns:
        st.error("El archivo CSV no contiene las columnas necesarias ('Local', 'Visitante').")
        return
        
    # Extraer equipos únicos
    teams_local = set(df_matches['Local'].dropna().unique())
    teams_visit = set(df_matches['Visitante'].dropna().unique())
    teams = sorted(list(teams_local | teams_visit))
    
    with col2:
        # 2. Selector de Equipo Dinámico
        selected_team = st.selectbox("Selecciona Equipo", teams)
        
    with col3:
        # 3. Selector de Filtros
        filter_option = st.selectbox("Estilos de Visualización", ["Todos los partidos", "Partidos jugados", "Partidos pendientes"])

    st.markdown("---")
    
    if not selected_team:
        return
        
    # Filtrar por equipo
    df_team = df_matches[(df_matches['Local'] == selected_team) | (df_matches['Visitante'] == selected_team)].copy()
    
    if df_team.empty:
        st.info(f"No hay partidos para {selected_team} en la temporada {selected_season}.")
        return

    # Preparar filtro de estado (GL, GV)
    if 'GL' not in df_team.columns or 'GV' not in df_team.columns:
        st.error("El archivo CSV no contiene las columnas de goles ('GL', 'GV').")
        return
        
    # 4. Lógica de Filtrado de Estado
    # En pandas, si la celda está vacía al leer CSV, suele ser NaN (float). 
    # El usuario pide:
    # "Jugados" = GL y GV tienen datos.
    # "Pendientes" = GL y GV están vacías o nulas.
    
    mask_played = df_team['GL'].notna() & df_team['GV'].notna()
    # Para pendientes usamos la inversa o verificamos isna o string vacio (por si se parseó como str)
    def is_empty_val(val):
        if pd.isna(val): return True
        if isinstance(val, str) and val.strip() == "": return True
        return False
        
    df_team['Is_Pending'] = df_team.apply(lambda row: is_empty_val(row['GL']) or is_empty_val(row['GV']), axis=1)
    
    if filter_option == "Partidos jugados":
        # Filtrar solo jugados
        df_team = df_team[~df_team['Is_Pending']]
    elif filter_option == "Partidos pendientes":
        # Filtrar pendientes
        df_team = df_team[df_team['Is_Pending']]
        
    if df_team.empty:
        st.info("No hay partidos que coincidan con el filtro seleccionado.")
        return
        
    st.markdown(f"#### Resultados para {selected_team} - {filter_option}")
    
    # 5. Renderizado en cuadrícula de los partidos usando HTML/JS para permitir descarga de imagen
    html_grid_content = ""
    for j, (_, row) in enumerate(df_team.iterrows()):
        jornada = row.get('Jornada', 'N/A')
        local_team = row['Local']
        visit_team = row['Visitante']
        
        # Determinar condición y rival
        if local_team == selected_team:
            condicion = "Local"
            rival = visit_team
        else:
            condicion = "Visitante"
            rival = local_team
            
        logo_b64 = get_img_b64(rival, selected_season)
        is_pending = row['Is_Pending']
        
        if not is_pending:
            gl = int(row['GL']) if pd.notna(row['GL']) else 0
            gv = int(row['GV']) if pd.notna(row['GV']) else 0
            res_str_local = f"<b>{gl}</b> - {gv}" if condicion == "Local" else f"{gl} - {gv}"
            res_str_visit = f"{gl} - <b>{gv}</b>" if condicion == "Visitante" else f"{gl} - {gv}"
            res_str = f"Res: {res_str_local if condicion == 'Local' else res_str_visit}"
        else:
            res_str = "<i>Pendiente</i>"
            
        header_color = "#38bdf8" if condicion == "Local" else "#f43f5e"
        header_icon = "🏠" if condicion == "Local" else "✈️"
        header_text = "Casa" if condicion == "Local" else "Fuera"
        
        card_html = f"""
        <div style="border: 1px solid rgba(250,250,250, 0.15); border-radius: 8px; padding: 12px; background-color: #f0f2f5; color: #0f172a; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <div style="color: {header_color}; font-size: 0.9em; margin-bottom: 8px;">
                {header_icon} <b>J{jornada}</b> | {header_text}
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="flex-shrink: 0;">
                    {"<img src='data:image/png;base64," + logo_b64 + "' width='45' height='45' style='object-fit: contain;'>" if logo_b64 else "<div style='width: 45px; height: 45px; background: #e2e8f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 0.7em; text-align: center; color: #0f172a;'>Sin<br>Img</div>"}
                </div>
                <div style="flex-grow: 1;">
                    <div style="font-weight: bold; font-size: 0.95em; margin-bottom: 4px;">vs {rival}</div>
                    <div style="font-size: 0.85em; color: #334155;">{res_str}</div>
                </div>
            </div>
        </div>
        """
        html_grid_content += card_html

    if filter_option == "Todos los partidos":
        filter_suffix = "Todos"
    elif filter_option == "Partidos jugados":
        filter_suffix = "Jugados"
    else:
        filter_suffix = "Pendientes"
    component_html_grid = f"""
    <html>
    <head>
        <style>
            body {{
                background-color: #ffffff;
                color: #0f172a;
                font-family: 'Source Sans Pro', sans-serif;
                margin: 0;
                padding: 10px;
            }}
            .btn-download {{
                background-color: #38bdf8;
                color: #0f172a;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                margin-bottom: 15px;
                font-family: inherit;
            }}
            .btn-download:hover {{
                background-color: #0ea5e9;
            }}
            .grid-container {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 15px;
                padding: 10px;
                background-color: #ffffff;
            }}
            ::-webkit-scrollbar {{
                width: 8px;
                height: 8px;
            }}
            ::-webkit-scrollbar-track {{
                background: #f0f2f5; 
            }}
            ::-webkit-scrollbar-thumb {{
                background: #475569; 
                border-radius: 4px;
            }}
            ::-webkit-scrollbar-thumb:hover {{
                background: #64748b; 
            }}
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    </head>
    <body>
        <button id="download-btn-grid" class="btn-download">
            📸 Descargar Resultados (PNG)
        </button>
        <div id="capture-area-grid" class="grid-container">
            {html_grid_content}
        </div>
        
        <script>
            document.getElementById('download-btn-grid').addEventListener('click', function() {{
                var btn = this;
                var originalText = btn.innerHTML;
                btn.innerHTML = '⏳ Generando...';
                btn.disabled = true;
                
                setTimeout(function() {{
                    html2canvas(document.getElementById('capture-area-grid'), {{
                        backgroundColor: '#ffffff',
                        scale: 2,
                        useCORS: true
                    }}).then(function(canvas) {{
                        var link = document.createElement('a');
                        link.download = 'Resultados_{selected_team}_{selected_season}_{filter_suffix}.png';
                        link.href = canvas.toDataURL('image/png');
                        link.click();
                        
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                    }}).catch(function(err) {{
                        console.error('Error capturando imagen:', err);
                        btn.innerHTML = '❌ Error';
                        setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                    }});
                }}, 100);
            }});
        </script>
    </body>
    </html>
    """
    
    st.iframe(component_html_grid, height=600)

    # --- NUEVA SECCIÓN GOLAVERAGE ---
    df_team_j = df_team.copy()
    df_team_j['Jornada_Num'] = pd.to_numeric(df_team_j['Jornada'], errors='coerce')
    df_second_half = df_team_j[df_team_j['Jornada_Num'] >= 20].sort_values('Jornada_Num')
    
    if not df_second_half.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"#### Golaverage - Partidos 2ª Vuelta ({filter_option})")
        st.info("Comparativa automática entre el resultado de la 2ª vuelta frente al de la 1ª vuelta para revisar el golaverage particular.")
        
        class_dir_temp = os.path.join("CSVs", "TemporadasClasificaciones")
        class_file_temp = os.path.join(class_dir_temp, f"Temporadas Clasificaciones.xlsx - [{selected_season}].csv")
        try:
            df_class_temp = pd.read_csv(class_file_temp, sep=";")
        except:
            df_class_temp = pd.DataFrame()

        dg_global = {}
        if not df_class_temp.empty:
            latest_df = df_class_temp.tail(20)
            for _, r in latest_df.iterrows():
                try:
                    gf = int(float(r['GF'])) if pd.notna(r['GF']) and str(r['GF']) != "" else 0
                    gc = int(float(r['GC'])) if pd.notna(r['GC']) and str(r['GC']) != "" else 0
                    dg = gf - gc
                    dg_global[r['Equipo']] = f"+{dg}" if dg > 0 else str(dg)
                except:
                    dg_global[r['Equipo']] = "0"
                
        html_grid_content_golaverage = ""
        
        for j, (_, row_vuelta) in enumerate(df_second_half.iterrows()):
            jornada_v = int(row_vuelta['Jornada_Num'])
            local_v = row_vuelta['Local']
            visit_v = row_vuelta['Visitante']
            
            if local_v == selected_team:
                condicion_v = "Local"
                rival = visit_v
            else:
                condicion_v = "Visitante"
                rival = local_v
                
            logo_b64 = get_img_b64(rival, selected_season)
            
            import difflib
            df_ida_pool = df_team_j[df_team_j['Jornada_Num'] < 20].copy()
            row_ida = None
            
            opps_ida = []
            for _, r_pool in df_ida_pool.iterrows():
                o = r_pool['Visitante'] if r_pool['Local'] == selected_team else r_pool['Local']
                opps_ida.append(o)
                
            best_match_opp = None
            for opp in opps_ida:
                opp_c, riv_c = str(opp).strip(), str(rival).strip()
                if opp_c == riv_c or riv_c in opp_c or opp_c in riv_c:
                    best_match_opp = opp
                    break
                    
            if not best_match_opp:
                closes = difflib.get_close_matches(str(rival).strip(), [str(o).strip() for o in opps_ida], n=1, cutoff=0.45)
                if closes:
                    for opp in opps_ida:
                        if str(opp).strip() == closes[0]:
                            best_match_opp = opp
                            break
                            
            if best_match_opp:
                mask = ((df_ida_pool['Local'] == selected_team) & (df_ida_pool['Visitante'] == best_match_opp)) | \
                       ((df_ida_pool['Local'] == best_match_opp) & (df_ida_pool['Visitante'] == selected_team))
                matches_ida_filtered = df_ida_pool[mask]
                if not matches_ida_filtered.empty:
                    row_ida = matches_ida_filtered.iloc[0]
            
            def get_res_data(r, cond):
                if r is None or pd.isna(r.get('GL')) or pd.isna(r.get('GV')) or str(r.get('GL')).strip() == "":
                    return "<i>Pendiente</i>", None, None
                gl = int(float(r['GL']))
                gv = int(float(r['GV']))
                if cond == "Local":
                    return f"<b>{gl}</b> - {gv}", gl, gv
                else:
                    return f"{gl} - <b>{gv}</b>", gv, gl

            res_str_vuelta, sel_v, riv_v = get_res_data(row_vuelta, condicion_v)
            
            if row_ida is not None:
                condicion_i = "Local" if row_ida['Local'] == selected_team else "Visitante"
                res_str_ida, sel_i, riv_i = get_res_data(row_ida, condicion_i)
                jornada_i_text = f"J{int(row_ida['Jornada_Num'])}"
            else:
                res_str_ida, sel_i, riv_i = "N/A", None, None
                jornada_i_text = "Ida"
                condicion_i = None
                
            header_color = "#38bdf8" if condicion_v == "Local" else "#f43f5e"
            header_icon = "🏠" if condicion_v == "Local" else "✈️"
            header_text = "Casa" if condicion_v == "Local" else "Fuera"
            
            # Calcular borde golaverage
            border_color = "rgba(250,250,250, 0.15)"
            if sel_v is not None and sel_i is not None:
                sel_total = sel_v + sel_i
                riv_total = riv_v + riv_i
                
                if sel_total > riv_total:
                    border_color = "#22c55e" # Gana
                elif sel_total < riv_total:
                    border_color = "#ef4444" # Pierde
            
            card_html_g = f"""
            <div style="border: 2px solid {border_color}; border-radius: 8px; padding: 11px; background-color: #f0f2f5; color: #0f172a; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2); display:flex; flex-direction:column; justify-content:space-between;">
                <div style="color: {header_color}; font-size: 0.9em; margin-bottom: 8px;">
                    {header_icon} <b>J{jornada_v}</b> | {header_text}
                </div>
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                    <div style="flex-shrink: 0;">
                        {"<img src='data:image/png;base64," + logo_b64 + "' width='45' height='45' style='object-fit: contain;'>" if logo_b64 else "<div style='width: 45px; height: 45px; background: #e2e8f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 0.7em; text-align: center; color: #0f172a;'>Sin<br>Img</div>"}
                    </div>
                    <div style="flex-grow: 1;">
                        <div style="font-weight: bold; font-size: 0.95em; margin-bottom: 4px;">vs {rival}</div>
                    </div>
                </div>
                <div style="font-size: 0.85em; color: #334155; background: #ffffff; padding: 8px; border-radius: 4px; display: grid; gap: 4px;">
                    <div style="display:flex; justify-content:space-between; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px;">
                        <span>VUELTA (J{jornada_v}):</span> <span>{res_str_vuelta}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; padding-top: 2px;">
                        <span>IDA ({jornada_i_text}):</span> <span style="opacity:0.9;">{res_str_ida}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding-top: 2px; font-size: 0.9em;">
                        <span title="Diferencia de Goles General">DG (Gen):</span> <span style="font-weight:bold;"><span style="color:#38bdf8;" title="{selected_team}">{dg_global.get(selected_team, '0')}</span> vs <span style="color:#f43f5e;" title="{rival}">{dg_global.get(rival, '0')}</span></span>
                    </div>
                </div>
            </div>
            """
            html_grid_content_golaverage += card_html_g

        component_html_grid_golaverage = f"""
        <html>
        <head>
            <style>
                body {{
                    background-color: #ffffff;
                    color: #0f172a;
                    font-family: 'Source Sans Pro', sans-serif;
                    margin: 0;
                    padding: 10px;
                }}
                .btn-download {{
                    background-color: #a855f7;
                    color: #0f172a;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-weight: bold;
                    margin-bottom: 15px;
                    font-family: inherit;
                }}
                .btn-download:hover {{
                    background-color: #9333ea;
                }}
                .grid-container {{
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                    gap: 15px;
                    padding: 10px;
                    background-color: #ffffff;
                }}
                ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
                ::-webkit-scrollbar-track {{ background: #f0f2f5; }}
                ::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 4px; }}
                ::-webkit-scrollbar-thumb:hover {{ background: #64748b; }}
            </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
        </head>
        <body>
            <button id="download-btn-grid" class="btn-download">
                📸 Descargar Golaverage (PNG)
            </button>
            <div id="capture-area-grid" class="grid-container">
                {html_grid_content_golaverage}
            </div>
            
            <script>
                document.getElementById('download-btn-grid').addEventListener('click', function() {{
                    var btn = this;
                    var originalText = btn.innerHTML;
                    btn.innerHTML = '⏳ Generando...';
                    btn.disabled = true;
                    
                    setTimeout(function() {{
                        html2canvas(document.getElementById('capture-area-grid'), {{
                            backgroundColor: '#ffffff',
                            scale: 2,
                            useCORS: true
                        }}).then(function(canvas) {{
                            var link = document.createElement('a');
                            link.download = 'Golaverage_{selected_team}_{selected_season}_{filter_suffix}.png';
                            link.href = canvas.toDataURL('image/png');
                            link.click();
                            
                            btn.innerHTML = originalText;
                            btn.disabled = false;
                        }}).catch(function(err) {{
                            console.error('Error capturando imagen:', err);
                            btn.innerHTML = '❌ Error';
                            setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                        }});
                    }}, 100);
                }});
            </script>
        </body>
        </html>
        """
        st.iframe(component_html_grid_golaverage, height=520)

    # --- NUEVA SECCIÓN EVOLUCIÓN DE POSICIÓN ---
    st.markdown("---")
    st.markdown("<h3><i class='bi bi-graph-up'></i> Evolución de Posición</h3>", unsafe_allow_html=True)
    st.info("Visualiza la evolución de las posiciones a lo largo de la temporada. Puedes añadir otro equipo para comparar.")
    
    col_evol1, col_evol2 = st.columns([1, 2])
    with col_evol1:
        compare_teams = st.multiselect("Añadir equipos para comparar (Opcional):", [t for t in teams if t != selected_team])
    
    # Obtener el DataFrame global
    df_global = load_data()
    
    if not df_global.empty:
        df_evol_season = df_global[df_global['Temporada'] == selected_season].copy()
        df_evol_sel = df_evol_season[df_evol_season['Equipo'] == selected_team].copy()
        
        if not df_evol_sel.empty:
            df_evol_sel = df_evol_sel.sort_values('Orden_Cronologico')
            plot_data = df_evol_sel
            
            for c_team in compare_teams:
                df_evol_comp = df_evol_season[df_evol_season['Equipo'] == c_team].copy()
                if not df_evol_comp.empty:
                    df_evol_comp = df_evol_comp.sort_values('Orden_Cronologico')
                    plot_data = pd.concat([plot_data, df_evol_comp])

            # Calcular tickvals/ticktext para mostrar número real de jornada
            ords_evol = sorted(plot_data['Orden_Cronologico'].unique())
            tick_map_evol = {}
            for _, rw in plot_data[['Orden_Cronologico', 'Jornada']].drop_duplicates().iterrows():
                tick_map_evol[rw['Orden_Cronologico']] = int(rw['Jornada'])
            ticktext_evol = [str(tick_map_evol.get(o, o)) for o in ords_evol]

            fig_pos = px.line(plot_data, x='Orden_Cronologico', y='Pos', color='Equipo',
                              markers=True, title=f"Posiciones a lo largo de la temporada {selected_season}",
                              hover_data={'Equipo': True, 'Jornada': True, 'Pos': True, 'PTS': True, 'Orden_Cronologico': False},
                              template="plotly_white")
            
            # Eje Y invertido (posición 1 arriba), eje X con labels reales
            fig_pos.update_yaxes(autorange="reversed", title="Posición", tickmode='linear', tick0=1, dtick=1, range=[20.5, 0.5])
            fig_pos.update_xaxes(title="Jornada", tickmode='array', tickvals=ords_evol, ticktext=ticktext_evol)
            
            fig_pos.update_layout(
                paper_bgcolor='#f0f2f5',
                plot_bgcolor='#f0f2f5',
                font=dict(color="#0f172a"),
                legend_title_text='Equipo',
                hovermode="x unified",
                margin=dict(t=50, b=40, l=40, r=40)
            )
            st.plotly_chart(fig_pos, width="stretch")
        else:
            st.warning("No hay datos de clasificación para el equipo en esta temporada.")

    # --- NUEVA SECCIÓN INTRACTIVA INFERIOR ---
    st.markdown("---")
    st.markdown("<h3><i class='bi bi-table'></i> Clasificación y Matriz de Pendientes</h3>", unsafe_allow_html=True)
    
    col_t, col_j = st.columns(2)
    
    class_dir = os.path.join("CSVs", "TemporadasClasificaciones")
    if not os.path.exists(class_dir):
        st.error(f"No se encontró el directorio de clasificaciones: {class_dir}")
        return
        
    with col_t:
        # Selector de Temporada (Clasificación)
        selected_class_season = st.selectbox(
            "Temporada (Clasificación)", 
            sorted(seasons, reverse=True), 
            index=sorted(seasons, reverse=True).index(selected_season) if selected_season in seasons else 0,
            key="class_season_sel"
        )
        
    class_file = os.path.join(class_dir, f"Temporadas Clasificaciones.xlsx - [{selected_class_season}].csv")
    matches_file = os.path.join(csv_dir, f"{selected_class_season}.csv")
    
    # Validation Rule: Both CLASSIFICATION and MATCHES files must exist
    if not os.path.exists(class_file) or not os.path.exists(matches_file):
        st.error("Error de inconsistencia de archivos: No se encontraron los datos correspondientes a la temporada seleccionada en ambas carpetas (Clasificaciones y Partidos).")
        return
        
    try:
        df_class = pd.read_csv(class_file, sep=";")
    except Exception as e:
        df_class = pd.DataFrame()
        st.error(f"Error al leer clasificaciones: {e}")
        return
        
    if df_class.empty or 'PJ' not in df_class.columns:
        st.warning("El archivo de clasificación no tiene el formato esperado (falta columna PJ).")
        return
        
    max_jornada = len(df_class) // 20
    if max_jornada == 0: max_jornada = 1
    jornadas_list = list(range(1, max_jornada + 1))
    
    with col_j:
        selected_jornada = st.selectbox("Jornada", jornadas_list, index=len(jornadas_list)-1)
        
    start_idx = (selected_jornada - 1) * 20
    end_idx = selected_jornada * 20
    df_class_j = df_class.iloc[start_idx:end_idx].copy()
    
    if df_class_j.empty:
        st.info("No hay datos de clasificación para esta jornada.")
        return
        
    if os.path.exists(matches_file):
        try:
            df_m = read_csv_dynamic(matches_file, sep=";")
        except:
            df_m = pd.DataFrame()
    else:
        df_m = pd.DataFrame()
        
    df_class_j = df_class_j.sort_values('Pos')
    liga_teams = df_class_j['Equipo'].tolist()
    
    team_logos = {t: get_img_b64(t, selected_class_season) for t in liga_teams}
    
    html_table = "<div style='overflow-x: auto;'><table style='width: 100%; border-collapse: collapse; text-align: center; color: #0f172a; font-size: 0.85rem;'>"
    
    # Calcular e inyectar DG (Diferencia de Goles) si no existe en el DataFrame
    if 'DG' not in df_class_j.columns and 'GF' in df_class_j.columns and 'GC' in df_class_j.columns:
        df_class_j['DG'] = pd.to_numeric(df_class_j['GF'], errors='coerce') - pd.to_numeric(df_class_j['GC'], errors='coerce')
        df_class_j['DG'] = df_class_j['DG'].map(lambda x: f"+{int(x)}" if int(x) > 0 else f"{int(x)}" if pd.notna(x) else "")
    elif 'DG' in df_class_j.columns:
        # Formatear la DG existente para que tenga + si es positivo, opcional pero mejor visualmente
        df_class_j['DG'] = pd.to_numeric(df_class_j['DG'], errors='coerce').map(lambda x: f"+{int(x)}" if pd.notna(x) and int(x) > 0 else f"{int(x)}" if pd.notna(x) else "")

    original_cols = ['Pos', 'Equipo', 'PTS', 'PJ', 'PG', 'PE', 'PP', 'GF', 'GC', 'DG', 'TA', 'TR']
    original_cols = [c for c in original_cols if c in df_class_j.columns]
    
    html_table += "<thead><tr>"
    for col in original_cols:
        html_table += f"<th style='padding: 8px; border-bottom: 2px solid #cbd5e1; text-align: left;'>{col}</th>"
        
    for t in liga_teams:
        logo = team_logos.get(t)
        if logo:
            html_table += f"<th style='padding: 8px; border-bottom: 2px solid #cbd5e1;' title='{t}'><img src='data:image/png;base64,{logo}' width='24' height='24'></th>"
        else:
            html_table += f"<th style='padding: 8px; border-bottom: 2px solid #cbd5e1;' title='{t}'>{t[:3]}</th>"
            
    html_table += "</tr></thead><tbody>"
    
    pending_matrix = {t: set() for t in liga_teams}
    if not df_m.empty:
        # Limpiar BOM (Byte Order Mark) de las columnas que puede corromper la lectura de 'Jornada'
        df_m.rename(columns=lambda x: str(x).strip('\ufeff').strip('ï»¿').strip(), inplace=True)
        
    if not df_m.empty and 'Jornada' in df_m.columns and 'Local' in df_m.columns and 'GL' in df_m.columns:
        import difflib
        def norm_team(name):
            name = str(name).strip()
            if name in liga_teams: return name
            
            # Alias directos para las conversiones más comunes
            alias_map = {
                "Athletic": "Athletic Club",
                "Celta Vigo": "Celta de Vigo",
                "Celta": "Celta de Vigo",
                "Rayo Vallecano": "Rayo Vallecano",
                "Alaves": "Alavés",
                "Cadiz": "Cádiz",
                "Recreativo de Huelva": "Recreativo",
                "At. Madrid": "Atlético de Madrid",
                "Atlético Madrid": "Atlético de Madrid",
                "Real Sociedad": "Real Sociedad",
                "Nastic de Tarragona": "Gimnàstic",
                "Espanyol": "Espanyol",
                "Deportivo Alaves": "Alavés",
                "Castellon": "Castellón",
                "Merida": "Mérida",
                "Betis": "Betis",
                "R. Madrid": "Real Madrid"
            }
            if name in alias_map and alias_map[name] in liga_teams:
                return alias_map[name]
                
            # Fuzzy match preventivo solo si es muy seguro
            matches = difflib.get_close_matches(name, liga_teams, n=1, cutoff=0.8)
            if matches: return matches[0]
            
            # Fallback sub-string match minucioso
            for lt in liga_teams:
                if name.lower() == lt.lower():
                    return lt
                    
            for lt in liga_teams:
                # Evitar falsos positivos como Real Madrid == Real Sociedad
                if len(name) > 4 and (name.lower() in lt.lower() or lt.lower() in name.lower()):
                    # Filtrar palabras genéricas
                    if name.lower() not in ["real", "club", "deportivo", "atletico"]:
                        return lt
                        
            return name

        for _, row in df_m.iterrows():
            j_match = row.get('Jornada')
            local = norm_team(row.get('Local'))
            visit = norm_team(row.get('Visitante'))
            gl = row.get('GL')
            
            try:
                j_match = int(float(j_match))
            except:
                continue
                
            # Regla de Negocio: Un partido se considera "no disputado" o "pendiente" si, 
            # en la fila correspondiente a ese partido, las columnas con cabeceras "GL" y "GV" están vacías.
            def is_empty(val):
                return pd.isna(val) or str(val).strip() == ""
                
            if is_empty(row.get('GL')) and is_empty(row.get('GV')):
                if local in pending_matrix:
                    pending_matrix[local].add(visit)
                if visit in pending_matrix:
                    pending_matrix[visit].add(local)
                        
    for _, row in df_class_j.iterrows():
        t_row = row['Equipo']
        html_table += "<tr style='border-bottom: 1px solid #cbd5e1;'>"
        
        for col in original_cols:
            val = row[col]
            if col == 'Equipo':
                logo = team_logos.get(t_row)
                if logo:
                    html_table += f"<td style='padding: 8px; text-align: left;'><div style='display: flex; align-items: center; gap: 8px;'><img src='data:image/png;base64,{logo}' width='20' height='20'> <b>{val}</b></div></td>"
                else:
                    html_table += f"<td style='padding: 8px; text-align: left;'><b>{val}</b></td>"
            else:
                html_table += f"<td style='padding: 8px; text-align: left;'>{val}</td>"
                
        for t_col in liga_teams:
            # 1. Equipo no juega contra sí mismo
            if t_row == t_col:
                html_table += "<td style='padding: 8px; background-color: #ffffff;'></td>"
            else:
                # 2. Si es listado explícitamente como partido PENDIENTE programado, mostrar escudo
                if t_col in pending_matrix.get(t_row, set()):
                    logo = team_logos.get(t_col)
                    if logo:
                        html_table += f"<td style='padding: 8px;' title='Pendiente: {t_col}'><img src='data:image/png;base64,{logo}' width='24' height='24'></td>"
                    else:
                        html_table += f"<td style='padding: 8px;' title='Pendiente: {t_col}'><small>{t_col[:3]}</small></td>"
                else:
                    html_table += "<td style='padding: 8px;'></td>"
                    
        html_table += "</tr>"
        
    html_table += "</tbody></table></div>"
    component_html = f"""
    <html>
    <head>
        <style>
            body {{
                background-color: #ffffff;
                color: #0f172a;
                font-family: 'Source Sans Pro', sans-serif;
                margin: 0;
                padding: 10px;
            }}
            .btn-download {{
                background-color: #38bdf8;
                color: #0f172a;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                margin-bottom: 15px;
                font-family: inherit;
            }}
            .btn-download:hover {{
                background-color: #0ea5e9;
            }}
            ::-webkit-scrollbar {{
                width: 8px;
                height: 8px;
            }}
            ::-webkit-scrollbar-track {{
                background: #f0f2f5; 
            }}
            ::-webkit-scrollbar-thumb {{
                background: #475569; 
                border-radius: 4px;
            }}
            ::-webkit-scrollbar-thumb:hover {{
                background: #64748b; 
            }}
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    </head>
    <body>
        <button id="download-btn" class="btn-download">
            📸 Descargar Matriz (PNG)
        </button>
        <div id="capture-area" style="padding: 10px; background-color: #ffffff;">
            {html_table}
        </div>
        
        <script>
            document.getElementById('download-btn').addEventListener('click', function() {{
                var btn = this;
                var originalText = btn.innerHTML;
                btn.innerHTML = '⏳ Generando...';
                btn.disabled = true;
                
                setTimeout(function() {{
                    html2canvas(document.getElementById('capture-area'), {{
                        backgroundColor: '#ffffff',
                        scale: 2,
                        useCORS: true
                    }}).then(function(canvas) {{
                        var link = document.createElement('a');
                        link.download = 'Matriz_Pendientes.png';
                        link.href = canvas.toDataURL('image/png');
                        link.click();
                        
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                    }}).catch(function(err) {{
                        console.error('Error capturando imagen:', err);
                        btn.innerHTML = '❌ Error';
                        setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                    }});
                }}, 100);
            }});
        </script>
    </body>
    </html>
    """
    
    st.iframe(component_html, height=750)

    # --- NUEVA SECCIÓN: TODOS LOS PARTIDOS PENDIENTES (MODO COLUMNAS) ---
    st.markdown("---")
    st.markdown("<h3><i class='bi bi-view-list'></i> Todos los Partidos Pendientes (Vista Columnas)</h3>", unsafe_allow_html=True)
    st.info("Vista global con todos los partidos que faltan por disputarse, ordenados por la clasificación actual.")
    
    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        total_equipos = len(liga_teams) if liga_teams else 20
        rango_pos = st.slider(
            "Selecciona posiciones a mostrar en la gráfica:",
            min_value=1,
            max_value=total_equipos,
            value=(1, total_equipos)
        )
        
    filtered_teams = liga_teams[rango_pos[0]-1 : rango_pos[1]]
    
    html_20_cols = ""
    
    # 1. Pre-calcular Pos y Pts para cabeceras y tarjetas
    team_info = {}
    for _, r in df_class_j.iterrows():
        team_info[r['Equipo']] = {'Pos': r['Pos'], 'PTS': r['PTS']}
        
    # 2. Pre-calcular W-D-L (Local/Visitante) de cada equipo
    stats_dict = {t: {'Home': {'W':0, 'D':0, 'L':0}, 'Away': {'W':0, 'D':0, 'L':0}} for t in liga_teams}
    if not df_m.empty:
        for _, r in df_m.iterrows():
            loc = norm_team(r.get('Local'))
            vis = norm_team(r.get('Visitante'))
            def is_empty_v(val): return pd.isna(val) or str(val).strip() == ""
            if not is_empty_v(r.get('GL')) and not is_empty_v(r.get('GV')):
                try:
                    gl = int(float(r.get('GL')))
                    gv = int(float(r.get('GV')))
                    if loc in stats_dict:
                        if gl > gv: stats_dict[loc]['Home']['W'] += 1
                        elif gl == gv: stats_dict[loc]['Home']['D'] += 1
                        else: stats_dict[loc]['Home']['L'] += 1
                    if vis in stats_dict:
                        if gv > gl: stats_dict[vis]['Away']['W'] += 1
                        elif gv == gl: stats_dict[vis]['Away']['D'] += 1
                        else: stats_dict[vis]['Away']['L'] += 1
                except: pass

    for team in filtered_teams:
        logo = team_logos.get(team)
        logo_html = f"<img src='data:image/png;base64,{logo}' width='50' height='50' style='object-fit: contain;'>" if logo else f"<div style='width: 50px; height: 50px; background: #e2e8f0; border-radius: 5px; display: flex; align-items: center; justify-content: center; font-size: 0.8em; text-align: center; color: #0f172a;'>{team[:3]}</div>"
        
        t_pos = team_info.get(team, {}).get('Pos', '-')
        t_pts = team_info.get(team, {}).get('PTS', '-')
        
        col_html = f"""
        <div style="min-width: 270px; flex: 0 0 auto; display: flex; flex-direction: column; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 12px; padding: 10px; background-color: #f0f2f5; border-radius: 8px; border: 1px solid rgba(250,250,250, 0.15);">
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: #ffffff; border-radius: 6px; padding: 4px 8px; border: 1px solid #cbd5e1; min-width: 45px;">
                    <span style="font-size: 1.1em; font-weight: bold; color: #38bdf8;">#{t_pos}</span>
                    <span style="font-size: 0.8em; color: #334155;">{t_pts}pt</span>
                </div>
                {logo_html}
                <div style="flex-grow: 1; font-weight: bold; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{team}">{team}</div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px;">
        """
        
        # Partidos pendientes de este equipo
        team_pending_matches = []
        if not df_m.empty:
            for _, r in df_m.iterrows():
                j_m = r.get('Jornada')
                loc = norm_team(r.get('Local'))
                vis = norm_team(r.get('Visitante'))
                
                # Regla de negocio: pendiente si GL y GV vacíos
                def is_empty_val(val):
                    return pd.isna(val) or str(val).strip() == ""
                
                if is_empty_val(r.get('GL')) and is_empty_val(r.get('GV')):
                    if loc == team:
                        team_pending_matches.append({'jornada': j_m, 'rival': vis, 'condicion': 'Local'})
                    elif vis == team:
                        team_pending_matches.append({'jornada': j_m, 'rival': loc, 'condicion': 'Visitante'})
                        
        # Sort if possible
        def get_j(m):
            try: return int(float(m['jornada']))
            except: return 999
        team_pending_matches.sort(key=get_j)
        
        for pm in team_pending_matches:
            rival = pm['rival']
            j_match = pm['jornada']
            cond = pm['condicion']
            r_logo = team_logos.get(rival)
            
            r_pos = team_info.get(rival, {}).get('Pos', '-')
            r_pts = team_info.get(rival, {}).get('PTS', '-')
            
            if cond == "Local":
                # Si nosotros jugamos como local, el rival es visitante
                r_stats = stats_dict.get(rival, {}).get('Away', {'W':0, 'D':0, 'L':0})
                stat_label = "Vis"
            else:
                r_stats = stats_dict.get(rival, {}).get('Home', {'W':0, 'D':0, 'L':0})
                stat_label = "Loc"
                
            w, d, l = r_stats['W'], r_stats['D'], r_stats['L']
            
            header_col = "#38bdf8" if cond == "Local" else "#f43f5e"
            header_ic = "🏠" if cond == "Local" else "✈️"
            header_txt = "Casa" if cond == "Local" else "Fuera"
            
            card = f"""
            <div style="border: 1px solid rgba(250,250,250, 0.15); border-radius: 8px; padding: 8px; background-color: #f0f2f5; color: #0f172a; box-shadow: 0 2px 4px -1px rgba(0, 0, 0, 0.1);">
                <div style="color: {header_col}; font-size: 0.8em; margin-bottom: 6px;">
                    {header_ic} <b>J{j_match}</b> | {header_txt}
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: #ffffff; border-radius: 4px; padding: 4px; min-width: 35px; border: 1px solid #cbd5e1;">
                        <span style="font-size: 0.85em; font-weight: bold; color: #a855f7;">#{r_pos}</span>
                        <span style="font-size: 0.7em; color: #334155;">{r_pts}p</span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; background-color: #ffffff; border-radius: 4px; padding: 4px; min-width: 48px; border: 1px solid #cbd5e1;">
                        <span style="font-size: 0.8em; font-weight: bold;"><span style="color:#22c55e;">{w}V</span><span style="color:#64748b;">{d}E</span><span style="color:#ef4444;">{l}D</span></span>
                        <span style="font-size: 0.65em; color: #475569;">({stat_label})</span>
                    </div>
                    <div style="flex-shrink: 0;">
                        {"<img src='data:image/png;base64," + r_logo + "' width='32' height='32' style='object-fit: contain;'>" if r_logo else "<div style='width: 32px; height: 32px; background: #e2e8f0; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 0.6em;'>Sin<br>Img</div>"}
                    </div>
                    <div style="flex-grow: 1; min-width: 0;">
                        <div style="font-weight: bold; font-size: 0.8em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{rival}">{rival}</div>
                    </div>
                </div>
            </div>
            """
            col_html += card
            
        col_html += "</div></div>"
        html_20_cols += col_html
        
    comp_html_20 = f"""
    <html>
    <head>
        <style>
            body {{
                background-color: #ffffff;
                color: #0f172a;
                font-family: 'Source Sans Pro', sans-serif;
                margin: 0;
                padding: 10px;
            }}
            .btn-download {{
                background-color: #38bdf8;
                color: #0f172a;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                margin-bottom: 15px;
                font-family: inherit;
            }}
            .btn-download:hover {{
                background-color: #0ea5e9;
            }}
            ::-webkit-scrollbar {{
                width: 8px;
                height: 8px;
            }}
            ::-webkit-scrollbar-track {{
                background: #f0f2f5; 
            }}
            ::-webkit-scrollbar-thumb {{
                background: #475569; 
                border-radius: 4px;
            }}
            ::-webkit-scrollbar-thumb:hover {{
                background: #64748b; 
            }}
            .grid-20-cols {{
                display: flex;
                gap: 15px;
                overflow-x: auto;
                padding-bottom: 15px;
                width: max-content;
            }}
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    </head>
    <body style="min-width: max-content;">
        <button id="download-20-cols-btn" class="btn-download">
            📸 Descargar 20 Columnas (PNG)
        </button>
        <div id="capture-area-20-cols" class="grid-20-cols">
            {html_20_cols}
        </div>
        
        <script>
            document.getElementById('download-20-cols-btn').addEventListener('click', function() {{
                var btn = this;
                var originalText = btn.innerHTML;
                btn.innerHTML = '⏳ Generando...';
                btn.disabled = true;
                
                setTimeout(function() {{
                    var captureArea = document.getElementById('capture-area-20-cols');
                    html2canvas(captureArea, {{
                        backgroundColor: '#ffffff',
                        scale: 2,
                        useCORS: true,
                        // Fix for scroll issues in html2canvas 
                        windowWidth: captureArea.scrollWidth,
                        width: captureArea.scrollWidth
                    }}).then(function(canvas) {{
                        var link = document.createElement('a');
                        link.download = 'Partidos_Pendientes_20_Columnas.png';
                        link.href = canvas.toDataURL('image/png');
                        link.click();
                        
                        btn.innerHTML = originalText;
                        btn.disabled = false;
                    }}).catch(function(err) {{
                        console.error('Error capturando imagen:', err);
                        btn.innerHTML = '❌ Error';
                        setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                    }});
                }}, 100);
            }});
        </script>
    </body>
    </html>
    """
    
    st.iframe(comp_html_20, height=800)

    # === NUEVA SECCIÓN: FORMATO RESULTADOS POR JORNADA EN COLUMNAS ===
    st.markdown("---")
    st.markdown("<h3><i class='bi bi-grid-3x3'></i> Resultados por Jornada (G-E-P)</h3>", unsafe_allow_html=True)
    
    col_c1, col_c2 = st.columns([1, 2])
    with col_c1:
        selected_res_season = st.selectbox(
            "Selecciona Temporada:", 
            sorted(seasons, reverse=True), 
            key="res_season"
        )
    with col_c2:
        rango_jornadas = st.slider(
            "Rango de Jornadas", 
            min_value=1, 
            max_value=38, 
            value=(1, 38), 
            key="res_jornadas"
        )
        
    j_start, j_end = rango_jornadas
    
    # Cargar partidos para resultados
    res_matches_file = os.path.join(csv_dir, f"{selected_res_season}.csv")
    res_class_file = os.path.join("CSVs", "TemporadasClasificaciones", f"Temporadas Clasificaciones.xlsx - [{selected_res_season}].csv")
    
    if os.path.exists(res_matches_file) and os.path.exists(res_class_file):
        try:
            df_res_m = read_csv_dynamic(res_matches_file, sep=";")
            df_res_c = pd.read_csv(res_class_file, sep=";")
        except Exception as e:
            df_res_m = pd.DataFrame()
            df_res_c = pd.DataFrame()
            
        if not df_res_m.empty and not df_res_c.empty and 'PJ' in df_res_c.columns:
            # Obtener ultima jornada de la clasificación para ordenamiento
            max_jornada = len(df_res_c) // 20
            if max_jornada == 0: max_jornada = 1
            latest_class = df_res_c.iloc[(max_jornada-1)*20 : max_jornada*20].sort_values('Pos')
            
            # Limpiar nombres de partidos a veces corrompidos (ya parseado o intentar limpiar BOM)
            df_res_m.rename(columns=lambda x: str(x).strip('\ufeff').strip('ï»¿').strip(), inplace=True)
            df_res_m['Jornada_Num'] = pd.to_numeric(df_res_m['Jornada'], errors='coerce')
            df_res_m['GL'] = pd.to_numeric(df_res_m['GL'], errors='coerce')
            df_res_m['GV'] = pd.to_numeric(df_res_m['GV'], errors='coerce')
            
            # Preparar un diccionario rápido de resultados
            # res_dict[equipo][jornada] = 'W', 'D', 'L', 'P' (Pendiente)
            from collections import defaultdict
            res_dict = defaultdict(dict)
            
            # Normalizar funcion pre-cacheando para velocidad
            lista_c = latest_class['Equipo'].tolist()
            import difflib
            
            def n_team(name):
                name = str(name).strip()
                if name in lista_c: return name
                # alias comunes y substring
                for c in lista_c:
                    if name in c or c in name: return c
                # fuzzy fallback
                matches = difflib.get_close_matches(name, lista_c, n=1, cutoff=0.5)
                if matches: return matches[0]
                return name
                
            for _, r in df_res_m.iterrows():
                j_num = r.get('Jornada_Num')
                if pd.isna(j_num): continue
                j_num = int(j_num)
                
                if not (j_start <= j_num <= j_end):
                    continue
                    
                loc = n_team(r.get('Local'))
                vis = n_team(r.get('Visitante'))
                
                gl = r.get('GL')
                gv = r.get('GV')
                
                if pd.isna(gl) or pd.isna(gv) or str(gl).strip() == "":
                    res_dict[loc][j_num] = 'P'
                    res_dict[vis][j_num] = 'P'
                else:
                    if gl > gv:
                        res_dict[loc][j_num] = 'W'
                        res_dict[vis][j_num] = 'L'
                    elif gl == gv:
                        res_dict[loc][j_num] = 'D'
                        res_dict[vis][j_num] = 'D'
                    else:
                        res_dict[loc][j_num] = 'L'
                        res_dict[vis][j_num] = 'W'
            
            jornadas_mostrar = list(range(j_start, j_end + 1))
            
            # Build HTML table
            res_html_table = "<div style='overflow-x: auto;'><table style='font-family: \"Source Sans Pro\", sans-serif; border-collapse: separate; border-spacing: 3px; text-align: center; color: #0f172a; font-size: 0.85rem;'>"
            
            # Header
            res_html_table += "<thead><tr>"
            res_html_table += "<th style='padding: 6px; background-color: #e2e8f0; position: sticky; left: 0; z-index: 10;'>Pos</th>"
            res_html_table += "<th style='padding: 6px; background-color: #e2e8f0; position: sticky; left: 35px; z-index: 10; text-align: left; min-width: 140px;'>Equipo</th>"
            for j in jornadas_mostrar:
                res_html_table += f"<th style='padding: 6px; background-color: #e2e8f0; min-width: 32px;'>J{j}</th>"
            res_html_table += "</tr></thead><tbody>"
            
            for _, r in latest_class.iterrows():
                t_nombre = r['Equipo']
                pos = r['Pos']
                logo_b64 = get_img_b64(t_nombre, selected_res_season)
                
                res_html_table += "<tr>"
                res_html_table += f"<td style='padding: 6px; background-color: #f0f2f5; font-weight: bold; position: sticky; left: 0; z-index: 5; border-radius:4px;'>{int(pos)}</td>"
                logo_str = f"<img src='data:image/png;base64,{logo_b64}' width='18' height='18' style='vertical-align: middle; margin-right: 5px;'>" if logo_b64 else ""
                res_html_table += f"<td style='padding: 6px 10px; background-color: #f0f2f5; text-align: left; font-weight: bold; position: sticky; left: 35px; z-index: 5; white-space: nowrap; border-radius:4px;'>{logo_str}{t_nombre}</td>"
                
                for j in jornadas_mostrar:
                    estado = res_dict.get(t_nombre, {}).get(j, '')
                    if estado == 'W':
                        res_html_table += "<td style='background-color: #22c55e; color: #0f172a; font-weight: bold; border-radius: 4px;' title='Ganado'>G</td>"
                    elif estado == 'L':
                        res_html_table += "<td style='background-color: #ef4444; color: #0f172a; font-weight: bold; border-radius: 4px;' title='Perdido'>P</td>"
                    elif estado == 'D':
                        res_html_table += "<td style='background-color: #64748b; color: #0f172a; font-weight: bold; border-radius: 4px;' title='Empatado'>E</td>"
                    elif estado == 'P':
                        res_html_table += "<td style='background-color: #e2e8f0; color: #475569; font-size: 0.8em; border-radius: 4px;' title='Pendiente'>-</td>"
                    else:
                        res_html_table += "<td style='background-color: #ffffff; border-radius: 4px;'></td>"
                        
                res_html_table += "</tr>"
                
            res_html_table += "</tbody></table></div>"
            
            comp_html_res = f"""
            <html>
            <head>
                <style>
                    body {{
                        background-color: #ffffff;
                        color: #0f172a;
                        font-family: inherit;
                        margin: 0;
                        padding: 10px;
                    }}
                    .btn-download {{
                        background-color: #22c55e;
                        color: #0f172a;
                        border: none;
                        padding: 8px 16px;
                        border-radius: 4px;
                        cursor: pointer;
                        font-weight: bold;
                        margin-bottom: 15px;
                        font-family: inherit;
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                    }}
                    .btn-download:hover {{ background-color: #16a34a; }}
                    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
                    ::-webkit-scrollbar-track {{ background: #f0f2f5; border-radius: 4px; }}
                    ::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 4px; }}
                    ::-webkit-scrollbar-thumb:hover {{ background: #64748b; }}
                </style>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
            </head>
            <body style="min-width: max-content;">
                <button id="download-res-btn" class="btn-download">
                    📸 Descargar Grid de Resultados (PNG)
                </button>
                <div id="capture-area-res" style="padding: 15px; background-color: #ffffff; width: max-content;">
                    {res_html_table}
                </div>
                
                <script>
                    document.getElementById('download-res-btn').addEventListener('click', function() {{
                        var btn = this;
                        var originalText = btn.innerHTML;
                        btn.innerHTML = '⏳ Generando...';
                        btn.disabled = true;
                        
                        setTimeout(function() {{
                            var captureArea = document.getElementById('capture-area-res');
                            html2canvas(captureArea, {{
                                backgroundColor: '#ffffff',
                                scale: 2,
                                useCORS: true,
                                windowWidth: captureArea.scrollWidth,
                                width: captureArea.scrollWidth
                            }}).then(function(canvas) {{
                                var link = document.createElement('a');
                                link.download = 'Resultados_G_E_P_{selected_res_season}_J{j_start}_al_J{j_end}.png';
                                link.href = canvas.toDataURL('image/png');
                                link.click();
                                
                                btn.innerHTML = originalText;
                                btn.disabled = false;
                            }}).catch(function(err) {{
                                console.error('Error capturando imagen:', err);
                                btn.innerHTML = '❌ Error';
                                setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                            }});
                        }}, 100);
                    }});
                </script>
            </body>
            </html>
            """
            st.iframe(comp_html_res, height=850)
            
        else:
            st.warning("No se encontraron datos para generar la vista de resultados (G-E-P).")
    else:
        st.error("No se encontraron los archivos necesarios para esta vista G-E-P en la temporada seleccionada.")

def render_predictions_view():
    st.markdown("<h2><i class='bi bi-magic'></i> Predicciones de Partido</h2>", unsafe_allow_html=True)
    st.markdown("Análisis estadístico predictivo basado en el estado de forma reciente (H2H y últimos partidos).")
    
    csv_dir = os.path.join("CSVs", "TemporadasPartidos")
    if not os.path.exists(csv_dir):
        st.error(f"No se encontró el directorio de partidos: {csv_dir}")
        return
        
    all_files = glob.glob(os.path.join(csv_dir, "*.csv"))
    if not all_files:
        st.warning("No hay archivos CSV en el directorio de temporadas.")
        return
        
    seasons = [os.path.basename(f).replace(".csv", "") for f in all_files]
    
    # 1. Controles Superiores
    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        selected_season = st.selectbox("Temporada", sorted(seasons, reverse=True), key="pred_season")
    
    file_path = os.path.join(csv_dir, f"{selected_season}.csv")
    try:
        df_matches = read_csv_dynamic(file_path, sep=";")
    except Exception as e:
        st.error(f"Error al leer el archivo {file_path}: {e}")
        return
        
    if 'Local' not in df_matches.columns or 'Visitante' not in df_matches.columns:
        st.error("El archivo CSV no contiene las columnas necesarias ('Local', 'Visitante').")
        return
        
    # Obtener equipos
    teams_local = set(df_matches['Local'].dropna().unique())
    teams_visit = set(df_matches['Visitante'].dropna().unique())
    teams = sorted(list(teams_local | teams_visit))
    
    with c2:
        home_team = st.selectbox("Equipo Local", teams, index=0 if len(teams)>0 else 0, key="pred_home")
    with c3:
        away_team = st.selectbox("Equipo Visitante", teams, index=1 if len(teams)>1 else 0, key="pred_away")
    with c4:
        period_options = {"Últimos 5": 5, "Últimos 10": 10, "Últimos 15": 15, "Últimos 20": 20, "Toda la Temporada": 999}
        selected_period = st.selectbox("Analizar Forma de", list(period_options.keys()), index=1, key="pred_period")
        n_matches = period_options[selected_period]

    if home_team == away_team:
        st.warning("Selecciona dos equipos diferentes.")
        return

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 3-Column Layout
    col_home, col_center, col_away = st.columns([1, 2, 1], gap="medium")
    
    def get_team_form(team, df, limit):
        # Filter matches where team played and it has a result (GL & GV not null)
        m = df[((df['Local'] == team) | (df['Visitante'] == team)) & df['GL'].notna() & df['GV'].notna()].copy()
        
        # Ensure proper sorting by Jornada
        m['Jornada_Num'] = pd.to_numeric(m['Jornada'], errors='coerce')
        m = m.dropna(subset=['Jornada_Num']).sort_values('Jornada_Num', ascending=False)
        m = m.head(limit)
        
        form_str = []
        gf = 0
        gc = 0
        wins, draws, losses = 0, 0, 0
        
        for _, row in m.iterrows():
            gl = pd.to_numeric(row['GL'], errors='coerce')
            gv = pd.to_numeric(row['GV'], errors='coerce')
            if pd.isna(gl) or pd.isna(gv): continue
            
            if row['Local'] == team:
                gf += gl; gc += gv
                if gl > gv:
                    form_str.append('W'); wins+=1
                elif gl == gv:
                    form_str.append('D'); draws+=1
                else:
                    form_str.append('L'); losses+=1
            else:
                gf += gv; gc += gl
                if gv > gl:
                    form_str.append('W'); wins+=1
                elif gv == gl:
                    form_str.append('D'); draws+=1
                else:
                    form_str.append('L'); losses+=1
                    
        return {'form': form_str, 'gf': int(gf), 'gc': int(gc), 'w': wins, 'd': draws, 'l': losses, 'pj': len(m)}

    home_form = get_team_form(home_team, df_matches, n_matches)
    away_form = get_team_form(away_team, df_matches, n_matches)

    # Rendering Side Columns
    def render_side_column(col, team_name, form_data, is_home):
        with col:
            logo_b64 = get_img_b64(team_name, selected_season)
            align = "center"
            
            # Team Header
            header_html = f"<div style='text-align: {align};'>"
            if logo_b64:
                header_html += f"<img src='data:image/png;base64,{logo_b64}' width='80' height='80' style='margin-bottom:10px;'>"
            else:
                header_html += f"<div style='width: 80px; height: 80px; margin: 0 auto 10px auto; background: #e2e8f0; border-radius: 5px; display: flex; align-items: center; justify-content: center;'>N/A</div>"
            
            header_html += f"<h3 style='margin:0; font-size:1.4rem; font-weight:700;'>{team_name}</h3>"
            header_html += f"<p style='color:#475569; font-size:0.9rem; margin-top:2px;'>{'Local' if is_home else 'Visitante'}</p></div>"
            st.markdown(header_html, unsafe_allow_html=True)
            
            # Form Dots
            dots_html = "<div style='display:flex; justify-content:center; gap:5px; margin: 15px 0;'>"
            for res in form_data['form'][::-1]: # Reverse to show oldest to newest left to right
                color = "#22c55e" if res == 'W' else "#64748b" if res == 'D' else "#ef4444"
                dots_html += f"<div style='width:24px; height:24px; border-radius:50%; background-color:{color}; color:#0f172a; font-size:12px; font-weight:bold; display:flex; align-items:center; justify-content:center;'>{res}</div>"
            if not form_data['form']:
                dots_html += "<span style='color:#64748b; font-size:0.9rem;'>No hay datos recientes</span>"
            dots_html += "</div>"
            st.markdown(dots_html, unsafe_allow_html=True)
            
            # Summary Box
            st.markdown(f"""
            <div style='background-color:#f0f2f5; padding:15px; border-radius:10px; border: 1px solid #cbd5e1;'>
                <div style='display:flex; justify-content:space-between; margin-bottom:10px; border-bottom:1px solid #cbd5e1; padding-bottom:5px;'>
                    <span style='color:#475569;'>Partidos:</span> <b style='color:#0f172a;'>{form_data['pj']}</b>
                </div>
                <div style='display:flex; justify-content:space-between; margin-bottom:10px; border-bottom:1px solid #cbd5e1; padding-bottom:5px;'>
                    <span style='color:#475569;'>Balance (V-E-D):</span> <b style='color:#0f172a;'>{form_data['w']} - {form_data['d']} - {form_data['l']}</b>
                </div>
                <div style='display:flex; justify-content:space-between; margin-bottom:10px; border-bottom:1px solid #cbd5e1; padding-bottom:5px;'>
                    <span style='color:#475569;'>Goles a Favor:</span> <b style='color:#22c55e;'>{form_data['gf']}</b>
                </div>
                <div style='display:flex; justify-content:space-between;'>
                    <span style='color:#475569;'>Goles Contra:</span> <b style='color:#ef4444;'>{form_data['gc']}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

    render_side_column(col_home, home_team, home_form, True)
    render_side_column(col_away, away_team, away_form, False)
    
    # Rendering Central Column (The Tabs)
    with col_center:
        tab_pred, tab_stat, tab_h2h = st.tabs(["🔮 Predicciones", "📊 Estadísticas", "⚔️ H2H"])
        
        with tab_pred:
            st.info("Predicciones basadas estadísticamente en el rendimiento de los últimos encuentros.")
            
            def calculate_probabilities(team_a_form, team_b_form):
                # Validar que haya partidos jugados
                pj_a = max(team_a_form['pj'], 1)
                pj_b = max(team_b_form['pj'], 1)
                
                # Match Winner (1X2)
                # Team A Win Prob = (Team A Win % + Team B Loss %) / 2
                p1 = ((team_a_form['w'] / pj_a) + (team_b_form['l'] / pj_b)) / 2
                px = ((team_a_form['d'] / pj_a) + (team_b_form['d'] / pj_b)) / 2
                p2 = ((team_a_form['l'] / pj_a) + (team_b_form['w'] / pj_b)) / 2
                
                # Normalize exactly to 100% just in case of rounding
                total_1x2 = p1 + px + p2
                if total_1x2 == 0:
                    p1, px, p2 = 0.33, 0.34, 0.33
                else:
                    p1, px, p2 = p1/total_1x2, px/total_1x2, p2/total_1x2
                    
                # Double Chance
                p1x = p1 + px
                p12 = p1 + p2
                px2 = px + p2
                
                return {
                    '1': p1 * 100, 'x': px * 100, '2': p2 * 100,
                    '1x': p1x * 100, '12': p12 * 100, 'x2': px2 * 100
                }
                
            def calculate_goals_probabilities(team_a, team_b, df, limit):
                def get_goal_stats(team):
                    m = df[((df['Local'] == team) | (df['Visitante'] == team)) & df['GL'].notna() & df['GV'].notna()].copy()
                    m['Jornada_Num'] = pd.to_numeric(m['Jornada'], errors='coerce')
                    m = m.dropna(subset=['Jornada_Num']).sort_values('Jornada_Num', ascending=False).head(limit)
                    
                    if m.empty: return {'btts': 0, 'o05': 0, 'o15': 0, 'o25': 0, 'o35': 0, 'pj': 0}
                    
                    m['GL'] = pd.to_numeric(m['GL'], errors='coerce')
                    m['GV'] = pd.to_numeric(m['GV'], errors='coerce')
                    m = m.dropna(subset=['GL', 'GV'])
                    
                    btts_count = len(m[(m['GL'] > 0) & (m['GV'] > 0)])
                    tg = m['GL'] + m['GV'] # Total Goals per match
                    
                    return {
                        'btts': btts_count / len(m),
                        'o05': len(m[tg > 0.5]) / len(m),
                        'o15': len(m[tg > 1.5]) / len(m),
                        'o25': len(m[tg > 2.5]) / len(m),
                        'o35': len(m[tg > 3.5]) / len(m),
                        'pj': len(m)
                    }
                    
                stats_a = get_goal_stats(team_a)
                stats_b = get_goal_stats(team_b)
                
                return {
                    'btts_yes': ((stats_a['btts'] + stats_b['btts']) / 2) * 100,
                    'o05': ((stats_a['o05'] + stats_b['o05']) / 2) * 100,
                    'o15': ((stats_a['o15'] + stats_b['o15']) / 2) * 100,
                    'o25': ((stats_a['o25'] + stats_b['o25']) / 2) * 100,
                    'o35': ((stats_a['o35'] + stats_b['o35']) / 2) * 100,
                }
                
            prob_1x2 = calculate_probabilities(home_form, away_form)
            prob_goals = calculate_goals_probabilities(home_team, away_team, df_matches, n_matches)
            
            # --- Ganador del Partido ---
            st.markdown("<h4 style='text-align:center;'>Ganador del Partido</h4>", unsafe_allow_html=True)
            
            fig_1x2 = go.Figure(go.Pie(
                values=[prob_1x2['1'], prob_1x2['x'], prob_1x2['2']],
                labels=['1', 'X', '2'],
                hole=.6,
                marker_colors=["#3b82f6", "#f59e0b", "#ef4444"],
                textinfo='label+percent',
                textposition='inside',
                textfont=dict(size=16, color='#0f172a'),
                hoverinfo="label+percent",
                showlegend=False
            ))
            
            fig_1x2.update_layout(
                margin=dict(t=20, b=20, l=10, r=10),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=260
            )

            st.plotly_chart(fig_1x2, width="stretch", config={'displayModeBar': False})
            
            c_p1, c_px, c_p2 = st.columns(3)
            with c_p1:
                st.markdown(f"<div style='text-align:center; font-weight:bold; color:#3b82f6; font-size:1.2rem;'>1<br><span style='font-size:0.7em; font-weight:normal; color:#475569'>{home_team}</span></div>", unsafe_allow_html=True)
            with c_px:
                st.markdown(f"<div style='text-align:center; font-weight:bold; color:#f59e0b; font-size:1.2rem;'>X<br><span style='font-size:0.7em; font-weight:normal; color:#475569'>Empate</span></div>", unsafe_allow_html=True)
            with c_p2:
                st.markdown(f"<div style='text-align:center; font-weight:bold; color:#ef4444; font-size:1.2rem;'>2<br><span style='font-size:0.7em; font-weight:normal; color:#475569'>{away_team}</span></div>", unsafe_allow_html=True)

            st.markdown("---")
            
            # --- Doble Oportunidad & Ambos Marcan ---
            c_doble, _, c_btts = st.columns([1.2, 0.1, 1.2])
            
            def render_progress(label, value, color):
                st.markdown(f"""
                <div style='margin-bottom:8px;'>
                    <div style='display:flex; justify-content:space-between; font-size:0.85em; margin-bottom:4px; color:#1e293b;'>
                        <span>{label}</span>
                        <span style='font-weight:bold;'>{int(value)}%</span>
                    </div>
                    <div style='width:100%; height:8px; background-color:#e2e8f0; border-radius:4px; overflow:hidden;'>
                        <div style='width:{value}%; height:100%; background-color:{color};'></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
            with c_doble:
                st.markdown("<h5 style='color:#0f172a; margin-bottom:15px;'>Doble Oportunidad</h5>", unsafe_allow_html=True)
                render_progress("1X (Local o Empate)", prob_1x2['1x'], "#38bdf8")
                render_progress("12 (Local o Visitante)", prob_1x2['12'], "#a855f7")
                render_progress("X2 (Empate o Visitante)", prob_1x2['x2'], "#f43f5e")
                
            with c_btts:
                st.markdown("<h5 style='color:#0f172a; margin-bottom:15px;'>Ambos Marcan</h5>", unsafe_allow_html=True)
                render_progress("Sí", prob_goals['btts_yes'], "#22c55e")
                render_progress("No", 100 - prob_goals['btts_yes'], "#ef4444")
                
            st.markdown("---")
            
            # --- Total Goles ---
            st.markdown("<h4 style='text-align:center; color:#0f172a;'>Línea de Goles (Over)</h4>", unsafe_allow_html=True)
            c_o1, c_o2, c_o3, c_o4 = st.columns(4)
            with c_o1: render_progress("Over 0.5", prob_goals['o05'], "#eab308")
            with c_o2: render_progress("Over 1.5", prob_goals['o15'], "#eab308")
            with c_o3: render_progress("Over 2.5", prob_goals['o25'], "#eab308")
            with c_o4: render_progress("Over 3.5", prob_goals['o35'], "#eab308")
            
        with tab_stat:
            st.info("Comparación de métricas promedio basadas en los últimos partidos seleccionados.")
            
            # Helper for displaying a stat row
            def stat_row(label, val1, val2, higher_is_better=True):
                color1 = "#4ade80" if (val1 > val2 and higher_is_better) or (val1 < val2 and not higher_is_better) else "#94a3b8" if val1 == val2 else "#f87171"
                color2 = "#4ade80" if (val2 > val1 and higher_is_better) or (val2 < val1 and not higher_is_better) else "#94a3b8" if val1 == val2 else "#f87171"
                
                st.markdown(f"""
                <div style='display:flex; justify-content:space-between; padding: 10px 15px; border-bottom: 1px solid #cbd5e1; align-items:center;'>
                    <div style='width:33%; text-align:left; font-weight:bold; color:{color1}; font-size:1.1em;'>{round(val1, 2)}</div>
                    <div style='width:33%; text-align:center; color:#334155; font-size:0.9em;'>{label}</div>
                    <div style='width:33%; text-align:right; font-weight:bold; color:{color2}; font-size:1.1em;'>{round(val2, 2)}</div>
                </div>
                """, unsafe_allow_html=True)
                
            pj_a = max(home_form['pj'], 1)
            pj_b = max(away_form['pj'], 1)
            
            st.markdown("<div style='display:flex; justify-content:space-between; padding:5px 15px; margin-top:10px;'><b style='color:#38bdf8'>Local</b><b style='color:#f43f5e'>Visitante</b></div>", unsafe_allow_html=True)
            stat_row("Goles A Favor (Media)", home_form['gf']/pj_a, away_form['gf']/pj_b, True)
            stat_row("Goles En Contra (Media)", home_form['gc']/pj_a, away_form['gc']/pj_b, False)
            
            diff_a = (home_form['gf'] - home_form['gc']) / pj_a
            diff_b = (away_form['gf'] - away_form['gc']) / pj_b
            stat_row("Diferencia de Goles (Media)", diff_a, diff_b, True)

        with tab_h2h:
            st.info(f"Últimos enfrentamientos directos entre {home_team} y {away_team}.")
            
            # Find H2H matches over ALL seasons if possible, but let's stick to current df_matches for simplicity or load all.
            # We'll load all files to give a proper historical H2H
            h2h_matches = []
            for f in all_files:
                season_name = os.path.basename(f).replace(".csv", "")
                try:
                    df_temp = read_csv_dynamic(f, sep=";")
                    df_temp['Temporada'] = season_name
                    m = df_temp[((df_temp['Local'] == home_team) & (df_temp['Visitante'] == away_team)) | ((df_temp['Local'] == away_team) & (df_temp['Visitante'] == home_team))].copy()
                    
                    for _, row in m.iterrows():
                        if pd.notna(row.get('GL')) and pd.notna(row.get('GV')): # Only played games
                            h2h_matches.append({
                                'season': season_name,
                                'jornada': row.get('Jornada', ''),
                                'local': row['Local'],
                                'visitante': row['Visitante'],
                                'gl': int(pd.to_numeric(row['GL'])),
                                'gv': int(pd.to_numeric(row['GV']))
                            })
                except:
                    pass
            
            # Sort by season descending
            h2h_matches.sort(key=lambda x: x['season'], reverse=True)
            
            if not h2h_matches:
                st.warning("No se encontraron enfrentamientos directos entre estos dos equipos en la base de datos.")
            else:
                for match in h2h_matches:
                    is_home_win = (match['local'] == home_team and match['gl'] > match['gv']) or (match['visitante'] == home_team and match['gv'] > match['gl'])
                    is_draw = match['gl'] == match['gv']
                    
                    color_stripe = "#22c55e" if is_home_win else "#64748b" if is_draw else "#ef4444"
                    
                    st.markdown(f"""
                    <div style='display:flex; background-color:#f0f2f5; border: 1px solid #cbd5e1; border-radius:6px; margin-bottom:10px; overflow:hidden;'>
                        <div style='width:6px; background-color:{color_stripe};'></div>
                        <div style='flex-grow:1; padding:10px 15px; display:flex; justify-content:space-between; align-items:center;'>
                            <div style='width:40%; text-align:right; font-weight:{"bold; color:#0f172a" if match['gl'] > match['gv'] else "normal; color:#475569"};'>{match['local']}</div>
                            <div style='width:20%; text-align:center; font-weight:bold; font-size:1.1em; background:#ffffff; color:#0f172a; border-radius:4px; padding:2px;'>
                                {match['gl']} - {match['gv']}
                            </div>
                            <div style='width:40%; text-align:left; font-weight:{"bold; color:#0f172a" if match['gv'] > match['gl'] else "normal; color:#475569"};'>{match['visitante']}</div>
                        </div>
                        <div style='padding:10px; font-size:0.8em; color:#475569; display:flex; flex-direction:column; justify-content:center; text-align:right; border-left: 1px solid #cbd5e1;'>
                            <div>{match['season']}</div>
                            <div>J{match['jornada']}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

def render_estudio_descensos(df):
    st.markdown("<h2><i class='bi bi-graph-down-arrow'></i> Análisis de Permanencia (Descensos)</h2>", unsafe_allow_html=True)
    st.markdown("Analiza la evolución y rendimiento de equipos históricos en peligro de descenso, basado en su situación en una Jornada clave.", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        jornada_eval = st.number_input("Jornada Clave (Evaluación de Inicio)", min_value=10, max_value=38, value=30, step=1)
    with col2:
        jornadas_inercia = st.number_input("Jornadas Previas (Análisis de Inercia)", min_value=1, max_value=jornada_eval-1, value=10, step=1)
    with col3:
        target_positions = st.slider("Rango de Posiciones Peligro", min_value=1, max_value=20, value=(13, 20))
        
    st.markdown("---")
    
    df_jornada = df[df['Jornada'] == jornada_eval]
    all_temporadas = sorted(df['Temporada'].unique(), reverse=True)
    
    default_seasons = [t for t in all_temporadas if t != "2025-2026"]
    selected_seasons = st.multiselect("Temporadas a incluir en el estudio:", all_temporadas, default=default_seasons)
    
    if not selected_seasons:
        st.warning("Seleccione al menos una temporada.")
        return
        
    df_jornada = df_jornada[df_jornada['Temporada'].isin(selected_seasons)]
    
    mask_pos = (df_jornada['Pos'] >= target_positions[0]) & (df_jornada['Pos'] <= target_positions[1])
    target_data = df_jornada[mask_pos]
    
    if target_data.empty:
        st.warning("No hay equipos en esas posiciones para esa jornada en las temporadas seleccionadas.")
        return
        
    st.subheader(f"Evolución Posicional (Jornada 1 a la {jornada_eval})")
    
    target_keys = target_data[['Temporada', 'Equipo']]
    df_evol = pd.merge(df, target_keys, on=['Temporada', 'Equipo'], how='inner')
    
    plot_seasons = st.multiselect("Filtrar gráfico interactivo por Temporada:", selected_seasons, default=selected_seasons[:3] if len(selected_seasons)>3 else selected_seasons)
    
    if plot_seasons:
        df_plot = df_evol[df_evol['Temporada'].isin(plot_seasons)].copy()
        df_plot = df_plot.sort_values('Orden_Cronologico')
        # Calcular tickvals/ticktext para mostrar número real de jornada
        ords_plot = sorted(df_plot['Orden_Cronologico'].unique())
        tick_map_plot = {}
        for _, rw in df_plot[['Orden_Cronologico', 'Jornada']].drop_duplicates().iterrows():
            tick_map_plot[rw['Orden_Cronologico']] = int(rw['Jornada'])
        ticktext_plot = [str(tick_map_plot.get(o, o)) for o in ords_plot]
        fig = px.line(df_plot, x='Orden_Cronologico', y='Pos', color='Equipo', line_dash='Temporada',
                      hover_data={'PTS': True, 'GF': True, 'GC': True, 'Jornada': True, 'Orden_Cronologico': False},
                      title="Evolución de Clasificación")
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(title="Jornada", tickmode='array', tickvals=ords_plot, ticktext=ticktext_plot)
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="#0f172a"))
        st.plotly_chart(fig, width="stretch")
        
    st.markdown("---")
    
    st.subheader(f"🔄 Análisis de Inercia (Jornadas {jornada_eval - jornadas_inercia} a {jornada_eval - 1})")
    
    start_inercia = jornada_eval - jornadas_inercia
    end_inercia = jornada_eval - 1
    
    df_end_inercia = df_evol[df_evol['Jornada'] == end_inercia].set_index(['Temporada', 'Equipo'])
    df_start_inercia = df_evol[df_evol['Jornada'] == max(1, start_inercia - 1)].set_index(['Temporada', 'Equipo']) 
    
    inercia_results = []
    for (t, e) in target_keys.values:
        try:
            r_end = df_end_inercia.loc[(t, e)]
            r_start = df_start_inercia.loc[(t, e)]
            
            pts_gain = r_end['PTS'] - r_start['PTS']
            pg_gain = r_end['PG'] - r_start['PG']
            gf_gain = r_end['GF'] - r_start['GF']
            
            inercia_results.append({
                'Temporada': t, 'Equipo': e,
                f'Pos J{jornada_eval}': target_data[(target_data['Temporada']==t)&(target_data['Equipo']==e)]['Pos'].values[0],
                'Dif. Puntos': pts_gain,
                'Victorias': pg_gain,
                'Dif. Goles a Favor': gf_gain
            })
        except KeyError:
            pass
            
    if inercia_results:
        df_inercia = pd.DataFrame(inercia_results).sort_values(by=['Dif. Puntos', 'Victorias'], ascending=[False, False])
        st.dataframe(df_inercia, width="stretch")
        
    st.markdown("---")
    
    st.subheader(f"🏁 Rendimiento Final (Jornada {jornada_eval} hasta Final)")
    
    partidos_dir = os.path.join("CSVs", "TemporadasPartidos")
    partidos_list = []
    if os.path.exists(partidos_dir):
        for t in selected_seasons:
            fn = os.path.join(partidos_dir, f"{t}.csv")
            if os.path.exists(fn):
                try:
                    df_p = read_csv_dynamic(fn, sep=';')
                    df_p['Temporada'] = t
                    partidos_list.append(df_p)
                except Exception:
                    pass
                    
    target_set = set((r['Temporada'], r['Equipo']) for _, r in target_keys.iterrows())
    final_stats = []
    
    if partidos_list:
        df_partidos = pd.concat(partidos_list, ignore_index=True)
        df_partidos['Jornada'] = pd.to_numeric(df_partidos['Jornada'], errors='coerce')
        df_partidos = df_partidos[df_partidos['Jornada'] >= jornada_eval]
        
        for (season, team) in target_set:
            cond_season = df_partidos['Temporada'] == season
            cond_home = cond_season & (df_partidos['Local'] == team)
            cond_away = cond_season & (df_partidos['Visitante'] == team)
            
            home_matches = df_partidos[cond_home]
            away_matches = df_partidos[cond_away]
            
            pts_home = sum(3 if row['GL'] > row['GV'] else 1 if row['GL'] == row['GV'] else 0 for _, row in home_matches.iterrows())
            pts_away = sum(3 if row['GV'] > row['GL'] else 1 if row['GV'] == row['GL'] else 0 for _, row in away_matches.iterrows())
            
            stats_dict = {
                'Temporada': season,
                'Equipo': team,
                'PTS Obtenidos': pts_home + pts_away,
                'PTS Casa': pts_home,
                'PTS Fuera': pts_away,
                'GF Casa': home_matches['GL'].sum() if not home_matches.empty else 0,
                'GC Casa': home_matches['GV'].sum() if not home_matches.empty else 0,
                'GF Fuera': away_matches['GV'].sum() if not away_matches.empty else 0,
                'GC Fuera': away_matches['GL'].sum() if not away_matches.empty else 0
            }
            
            df_season = df_evol[(df_evol['Temporada'] == season) & (df_evol['Equipo'] == team)]
            pos_final = df_season['Pos'].iloc[-1] if not df_season.empty else "N/A"
            stats_dict['Posición Final'] = pos_final
            stats_dict['¿Descendió?'] = "❌ Sí" if (isinstance(pos_final, (int, float)) and pos_final >= 18) else "✅ Sálv."
            
            final_stats.append(stats_dict)
            
    if final_stats:
        df_final = pd.DataFrame(final_stats).sort_values(by=['Temporada', 'Equipo'])
        st.dataframe(df_final, width="stretch")
        
        try:
            import io
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                target_data.to_excel(writer, sheet_name=f'Posiciones J{jornada_eval}', index=False)
                if inercia_results:
                    df_inercia.to_excel(writer, sheet_name='Inercia (Tendencia)', index=False)
                df_final.to_excel(writer, sheet_name='Rendimiento Final', index=False)
                df_evol.to_excel(writer, sheet_name='Evolucion Completa', index=False)
            
            buffer.seek(0)
            
            st.markdown("---")
            col_btn, _ = st.columns([1, 2])
            with col_btn:
                st.download_button(
                    label="📥 Descargar Análisis en Excel",
                    data=buffer,
                    file_name=f"analisis_permanencia_J{jornada_eval}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
        except Exception as e:
            st.error(f"No se pudo generar el archivo Excel: {e}")
    else:
        st.info("No se hallaron partidos en 'TemporadasPartidos' para computar estadísticas de Local/Visitante.")

def render_historico_posiciones(df):
    """Histórico de equipos en una posición dada en una jornada concreta."""
    st.markdown("<h2><i class='bi bi-clock-history'></i> Histórico de Posiciones</h2>", unsafe_allow_html=True)
    st.markdown("Consulta qué equipos estuvieron en una posición concreta en una jornada determinada a lo largo de toda la historia de la liga, incluyendo cómo terminaron la temporada y los resultados que les quedaban por disputar.")
    st.markdown("---")

    # ------------------------------------------------------------------
    # Filtros
    # ------------------------------------------------------------------
    max_jornada_global = int(df['Jornada'].max())

    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        pos_filter = st.number_input("Posición a filtrar:", min_value=1, max_value=20, value=18, step=1, key="hpos_pos")
    with c2:
        jornada_filter = st.number_input("Jornada:", min_value=1, max_value=max_jornada_global, value=min(30, max_jornada_global), step=1, key="hpos_jor")
    with c3:
        margin = st.number_input("Margen de puntos (±):", min_value=0, max_value=20, value=3, step=1, key="hpos_margin",
                                 help="Incluye equipos que en esa jornada tenían entre [Puntos - margen] y [Puntos + margen]")
    with c4:
        st.write("")  # spacer
        st.write("")
        buscar = st.button("🔍 Buscar", type="primary", key="hpos_buscar")

    if not buscar and 'hpos_results' not in st.session_state:
        st.info("Ajusta los filtros y pulsa **Buscar** para ver el histórico.")
        return

    # ------------------------------------------------------------------
    # Lógica de datos
    # ------------------------------------------------------------------

    def get_match_results_from_jornada(df_team_season, from_jornada):
        """
        Dada la secuencia de clasificaciones de un equipo en una temporada,
        devuelve los resultados (G/E/P) para cada jornada POSTERIOR a from_jornada,
        usando las diferencias en PG, PE, PP entre jornadas consecutivas.
        Devuelve lista de tuplas (jornada, resultado) ordenadas por Orden_Cronologico.
        """
        # Ordenar por Orden_Cronologico
        team_seq = df_team_season.sort_values('Orden_Cronologico').copy()
        results = []
        prev = None
        for _, row in team_seq.iterrows():
            oc = row['Orden_Cronologico']
            jor = int(row['Jornada'])
            if oc <= from_jornada:
                prev = row
                continue
            # Esta jornada es posterior a la seleccionada
            if prev is not None:
                delta_pg = int(row['PG']) - int(prev['PG'])
                delta_pe = int(row['PE']) - int(prev['PE'])
                delta_pp = int(row['PP']) - int(prev['PP'])
                if delta_pg >= 1:
                    res = 'G'
                elif delta_pe >= 1:
                    res = 'E'
                elif delta_pp >= 1:
                    res = 'P'
                else:
                    # No hay diferencia clara, marcar como desconocido
                    res = '?'
            else:
                # No hay referencia previa
                res = '?'
            results.append((jor, res))
            prev = row
        return results

    # Obtener OC correspondiente a la jornada seleccionada (para comparación)
    # Usamos Orden_Cronologico de la jornada seleccionada
    # (puede diferir de Jornada en 2025-2026)
    jornada_oc_map = df.drop_duplicates(subset=['Temporada', 'Jornada'])[['Temporada', 'Jornada', 'Orden_Cronologico']]

    # Filtrar DF por jornada seleccionada
    df_jornada = df[df['Jornada'] == jornada_filter].copy()

    if df_jornada.empty:
        st.warning(f"No hay datos para la Jornada {jornada_filter}.")
        return

    # Encontrar equipo(s) en la posición exacta en esa jornada
    df_pos = df_jornada[df_jornada['Pos'] == pos_filter].copy()
    if df_pos.empty:
        st.warning(f"Ningún equipo estuvo en la posición {pos_filter} en la Jornada {jornada_filter}.")
        return

    # Aplicar margen de puntos
    puntos_ref_min = df_pos['PTS'].min() - margin
    puntos_ref_max = df_pos['PTS'].max() + margin
    df_pos_margin = df_jornada[
        (df_jornada['Pos'] == pos_filter) |
        (
            (df_jornada['PTS'] >= puntos_ref_min) &
            (df_jornada['PTS'] <= puntos_ref_max) &
            (df_jornada['Pos'] >= pos_filter - 1) &
            (df_jornada['Pos'] <= pos_filter + 1)
        )
    ].copy()

    # Equipos descendidos por temporada (posiciones 18, 19, 20 al final)
    # "Final de temporada" = jornada máxima de cada temporada
    last_jornada_per_season = df.groupby('Temporada')['Orden_Cronologico'].max().reset_index()
    last_jornada_per_season.columns = ['Temporada', 'OC_Max']

    relegation_data = {}
    for _, lrow in last_jornada_per_season.iterrows():
        temp = lrow['Temporada']
        oc_max = lrow['OC_Max']
        df_final = df[(df['Temporada'] == temp) & (df['Orden_Cronologico'] == oc_max)]
        rel = {}
        for rp in [18, 19, 20]:
            eq_rp = df_final[df_final['Pos'] == rp]['Equipo'].values
            rel[rp] = eq_rp[0] if len(eq_rp) > 0 else '-'
        relegation_data[temp] = rel

    # Final de temporada por equipo (última jornada disponible)
    df_final_season = df.loc[df.groupby(['Temporada', 'Equipo'])['Orden_Cronologico'].idxmax()].copy()
    df_final_season = df_final_season[['Temporada', 'Equipo', 'Pos', 'PTS']].rename(
        columns={'Pos': 'Pos_Final', 'PTS': 'PTS_Final'}
    )

    # ------------------------------------------------------------------
    # Construir filas del resultado
    # ------------------------------------------------------------------
    rows = []

    for _, row in df_pos_margin.iterrows():
        temp = row['Temporada']
        equipo = row['Equipo']
        pos_j = int(row['Pos'])
        pts_j = int(row['PTS'])
        jornada_j = int(row['Jornada'])
        oc_j = int(row['Orden_Cronologico'])

        # Posición y puntos finales
        final_row = df_final_season[
            (df_final_season['Temporada'] == temp) & (df_final_season['Equipo'] == equipo)
        ]
        pos_final = int(final_row['Pos_Final'].values[0]) if not final_row.empty else '-'
        pts_final = int(final_row['PTS_Final'].values[0]) if not final_row.empty else '-'

        # Descendidos de esa temporada
        rel = relegation_data.get(temp, {18: '-', 19: '-', 20: '-'})
        desc18 = rel.get(18, '-')
        desc19 = rel.get(19, '-')
        desc20 = rel.get(20, '-')

        # Resultados de partidos posteriores
        df_team = df[(df['Temporada'] == temp) & (df['Equipo'] == equipo)].copy()
        match_results = get_match_results_from_jornada(df_team, oc_j)
        partidos_count = len(match_results)

        rows.append({
            'Temporada': temp,
            'Equipo': equipo,
            'Posición': pos_j,
            'Puntos J': pts_j,
            'Jornada': jornada_j,
            'Posición Final': pos_final,
            'Puntos Finales': pts_final,
            'Descendido 18': desc18,
            'Descendido 19': desc19,
            'Descendido 20': desc20,
            '_partidos': match_results,
            '_partidos_count': partidos_count,
        })

    if not rows:
        st.warning("No se encontraron datos para los filtros seleccionados.")
        return

    df_result = pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Renderizar tabla HTML con ordenación por clic en cabecera
    # ------------------------------------------------------------------
    st.markdown(f"**{len(df_result)} registro(s) encontrados** | Pos {pos_filter} en J{jornada_filter} (margen ±{margin} pts)")
    st.caption("Haz clic en el título de una columna para ordenar la tabla.")

    # Colores para badges
    badge_styles = {
        'G': ('background:#16a34a;color:#fff;', 'G'),
        'E': ('background:#ea580c;color:#fff;', 'E'),
        'P': ('background:#dc2626;color:#fff;', 'P'),
        '?': ('background:#64748b;color:#fff;', '?'),
    }

    def build_partidos_html(match_results):
        if not match_results:
            return "<span style='color:#94a3b8;font-size:12px'>— Sin partidos —</span>"
        badges = []
        for (jor, res) in match_results:
            style, letter = badge_styles.get(res, badge_styles['?'])
            badges.append(
                f"<span title='J{jor}' style='{style}display:inline-flex;align-items:center;justify-content:center;"
                f"width:24px;height:24px;border-radius:50%;font-size:11px;font-weight:700;"
                f"margin:1px;cursor:default;'>{letter}</span>"
            )
        return "".join(badges)

    # Estilos de celdas
    td_style = "padding:7px 12px;font-size:13px;color:#1e293b;border-bottom:1px solid #f1f5f9;white-space:nowrap;vertical-align:middle;"
    td_center = td_style + "text-align:center;"

    # Construir filas HTML — también guardamos data-values para el sort JS
    # Columnas sortables (índice 0-9), la 10 (Partidos) no es sortable
    html_rows = ""
    for i, (_, row) in enumerate(df_result.iterrows()):
        row_bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        partidos_html = build_partidos_html(row['_partidos'])

        pos_final_val = row['Posición Final']
        pos_final_color = "#dc2626" if isinstance(pos_final_val, int) and pos_final_val >= 18 else "#16a34a"
        pos_final_html = f"<span style='color:{pos_final_color};font-weight:600'>{pos_final_val}</span>"

        # data-val se usa para ordenar; para Posición Final guardamos el número real
        pf_sort = pos_final_val if isinstance(pos_final_val, int) else 99

        html_rows += f"""
        <tr style='background:{row_bg}' class='hrow'>
            <td style='{td_style}' data-val="{row['Temporada']}"><strong>{row['Temporada']}</strong></td>
            <td style='{td_style}' data-val="{row['Equipo']}">{row['Equipo']}</td>
            <td style='{td_center}' data-val="{row['Posición']}">{row['Posición']}</td>
            <td style='{td_center}' data-val="{row['Puntos J']}"><strong>{row['Puntos J']}</strong></td>
            <td style='{td_center}' data-val="{row['Jornada']}">{row['Jornada']}</td>
            <td style='{td_center}' data-val="{pf_sort}">{pos_final_html}</td>
            <td style='{td_center}' data-val="{row['Puntos Finales']}">{row['Puntos Finales']}</td>
            <td style='{td_style};font-size:12px' data-val="{row['Descendido 18']}">{row['Descendido 18']}</td>
            <td style='{td_style};font-size:12px' data-val="{row['Descendido 19']}">{row['Descendido 19']}</td>
            <td style='{td_style};font-size:12px' data-val="{row['Descendido 20']}">{row['Descendido 20']}</td>
            <td style='{td_style}'>{partidos_html}</td>
        </tr>"""

    # Cabeceras: las primeras 10 son sortables, la 11 (Partidos) no
    sortable_headers = ['Temporada', 'Equipo', 'Posición', 'Puntos J', 'Jornada',
                        'Posición Final', 'Puntos Finales', 'Descendido 18', 'Descendido 19', 'Descendido 20']

    header_cells = ""
    for idx, h in enumerate(sortable_headers):
        header_cells += (
            f"<th onclick='hposSort({idx})'>"
            f"{h} <span class='arr' id='hpos-arr-{idx}'>&#x21C5;</span></th>"
        )
    header_cells += "<th class='no-sort'>Partidos</th>"

    table_id = "hpos-table"

    full_table = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; padding:4px; font-family:Inter,sans-serif; background:#f8f9fa; }}
  #hpos-table {{ width:100%; border-collapse:collapse; }}
  #hpos-table thead th {{
    padding:8px 12px; font-size:13px; font-weight:600; color:#0f172a;
    border-bottom:2px solid #e2e8f0; white-space:nowrap; background:#f1f5f9;
    cursor:pointer; user-select:none; text-align:left;
  }}
  #hpos-table thead th:hover {{ background:#e2e8f0; }}
  #hpos-table thead th.no-sort {{ cursor:default; }}
  #hpos-table thead th.no-sort:hover {{ background:#f1f5f9; }}
  #hpos-table td {{
    padding:7px 12px; font-size:13px; color:#1e293b;
    border-bottom:1px solid #f1f5f9; white-space:nowrap; vertical-align:middle;
  }}
  .arr {{ font-size:10px; color:#94a3b8; margin-left:4px; }}
  .arr.active {{ color:#0ea5e9; }}
  .wrap {{ overflow-x:auto; border-radius:10px; border:1px solid #e2e8f0;
           box-shadow:0 1px 4px rgba(0,0,0,.06); }}
</style>
</head>
<body>
<div class="wrap">
<table id="{table_id}">
  <thead><tr>{header_cells}</tr></thead>
  <tbody id="hpos-tbody">{html_rows}</tbody>
</table>
</div>
<script>
var _sortCol = -1;
var _sortAsc  = true;

function hposSort(colIdx) {{
  if (_sortCol === colIdx) {{
    _sortAsc = !_sortAsc;
  }} else {{
    _sortCol = colIdx;
    _sortAsc = true;
  }}

  // Reset all arrows
  document.querySelectorAll('.arr').forEach(function(el) {{
    el.textContent = '\u21C5';
    el.classList.remove('active');
  }});
  var arrEl = document.getElementById('hpos-arr-' + colIdx);
  if (arrEl) {{
    arrEl.textContent = _sortAsc ? '\u25B2' : '\u25BC';
    arrEl.classList.add('active');
  }}

  var tbody = document.getElementById('hpos-tbody');
  var rows  = Array.from(tbody.querySelectorAll('tr'));

  rows.sort(function(a, b) {{
    var aCell = a.querySelectorAll('td')[colIdx];
    var bCell = b.querySelectorAll('td')[colIdx];
    var aVal  = aCell ? (aCell.getAttribute('data-val') || '') : '';
    var bVal  = bCell ? (bCell.getAttribute('data-val') || '') : '';
    var aNum  = parseFloat(aVal);
    var bNum  = parseFloat(bVal);
    var cmp   = (!isNaN(aNum) && !isNaN(bNum)) ? (aNum - bNum)
              : aVal.localeCompare(bVal, 'es', {{sensitivity:'base'}});
    return _sortAsc ? cmp : -cmp;
  }});

  rows.forEach(function(row, i) {{
    row.style.background = (i % 2 === 0) ? '#ffffff' : '#f8fafc';
    tbody.appendChild(row);
  }});
}}
</script>
</body>
</html>"""

    # Calcular altura dinámica: ~36px por fila + 80px cabecera y padding
    table_height = min(max(len(df_result) * 36 + 80, 200), 700)
    components.html(full_table, height=table_height, scrolling=True)

    # Leyenda
    st.markdown(
        "<div style='margin-top:10px;font-size:12px;color:#64748b'>"
        "<span style='background:#16a34a;color:#fff;border-radius:50%;padding:2px 7px;margin-right:4px;font-weight:700'>G</span> Ganado &nbsp;"
        "<span style='background:#ea580c;color:#fff;border-radius:50%;padding:2px 7px;margin-right:4px;font-weight:700'>E</span> Empatado &nbsp;"
        "<span style='background:#dc2626;color:#fff;border-radius:50%;padding:2px 7px;margin-right:4px;font-weight:700'>P</span> Perdido"
        "</div>",
        unsafe_allow_html=True
    )


if df.empty:
    st.error("⚠️ No se encontraron datos. Verifique la carpeta 'CSVs/TemporadasClasificaciones'")
else:
    _nav = st.session_state.active_section
    if _nav == "Inicio":
        render_home(df)
    elif _nav == "Análisis Histórico":
        render_historical_analysis(df)
    elif _nav == "Comparador Gemelos":
        render_twins_comparator(df)
    elif _nav == "Estadísticas":
        render_statistics_section()
    elif _nav == "Estudio Descensos":
        render_estudio_descensos(df)
    elif _nav == "Modelo Predictivo":
        render_predictive_model()
    elif _nav == "Árbitros":
        render_referees_section()
    elif _nav == "Calendario":
        render_calendar_view()
    elif _nav == "Predicciones":
        render_predictions_view()
    elif _nav == "Histórico: Posiciones":
        render_historico_posiciones(df)

