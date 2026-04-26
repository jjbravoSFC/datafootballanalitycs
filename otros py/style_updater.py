import codecs

filepath = r"c:\OneDrive\OneDrive\Desarrollos Locales\Temporadas Clasificaciones\app.py"

with codecs.open(filepath, 'r', 'utf-8') as f:
    code = f.read()

# 1. Update CSS
old_css = """    h1, h2, h3, h4, h5, h6, p, span, div, li {
        color: #f1f5f9 !important;
    }"""
    
new_css = """    h1, h2, h3, h4, h5, h6, p, span, div, li, label, .stMarkdown p {
        color: #94a3b8 !important; /* Slate 400 to match menu text */
    }
    
    h1, h2, h3, h4, h5, h6, h1 span, h2 span, h3 span, h4 span, h5 span, h6 span {
        color: #f1f5f9 !important; /* Keep headers whiteish */
    }

    /* Boostrap Icons inside Markdown */
    i.bi {
        color: #38bdf8 !important; /* Sky 400 to match menu icons */
        margin-right: 0.4rem;
    }

    /* Streamlit Material Icons */
    .stIcon {
        color: #38bdf8 !important;
    }
    span.material-symbols-rounded {
        color: #38bdf8 !important;
    }"""

code = code.replace(old_css, new_css)

# Replace Headers
replacements = [
    ('st.markdown("## 🏠 Bienvenido al Panel de Análisis Histórico")', 'st.markdown("<h2><i class=\'bi bi-house\'></i> Bienvenido al Panel de Análisis Histórico</h2>", unsafe_allow_html=True)'),
    ('st.header("📈 Análisis Histórico por Equipo")', 'st.markdown("<h2><i class=\'bi bi-bar-chart-line\'></i> Análisis Histórico por Equipo</h2>", unsafe_allow_html=True)'),
    ('st.header("👯 Comparador de \'Gemelos\' Históricos")', 'st.markdown("<h2><i class=\'bi bi-people\'></i> Comparador de \'Gemelos\' Históricos</h2>", unsafe_allow_html=True)'),
    ('st.header("📊 Estadísticas de Competición")', 'st.markdown("<h2><i class=\'bi bi-graph-up\'></i> Estadísticas de Competición</h2>", unsafe_allow_html=True)'),
    ('st.header("🧠 Modelo Predictivo (Sport Analytics)")', 'st.markdown("<h2><i class=\'bi bi-cpu\'></i> Modelo Predictivo (Sport Analytics)</h2>", unsafe_allow_html=True)'),
    
    ('st.subheader(f"📊 Equipos en Posición {ref_pos}")', 'st.markdown(f"<h3><i class=\'bi bi-bar-chart-fill\'></i> Equipos en Posición {ref_pos}</h3>", unsafe_allow_html=True)'),
    ('st.subheader(f"📊 Rendimiento similar a {ref_pts} Pts")', 'st.markdown(f"<h3><i class=\'bi bi-bar-chart-fill\'></i> Rendimiento similar a {ref_pts} Pts</h3>", unsafe_allow_html=True)'),
    ('st.header("🔮 Proyección: ¿Dónde acabaron estos equipos?")', 'st.markdown("<h2><i class=\'bi bi-eye\'></i> Proyección: ¿Dónde acabaron estos equipos?</h2>", unsafe_allow_html=True)'),
    ('st.subheader(f"🏁 Final de los Equipos en Posición {ref_pos}")', 'st.markdown(f"<h3><i class=\'bi bi-flag\'></i> Final de los Equipos en Posición {ref_pos}</h3>", unsafe_allow_html=True)'),
    ('st.subheader(f"🏁 Final de los Equipos con {ref_pts} Pts")', 'st.markdown(f"<h3><i class=\'bi bi-flag\'></i> Final de los Equipos con {ref_pts} Pts</h3>", unsafe_allow_html=True)'),
    ('st.header("📉 Zona de Descenso Histórica")', 'st.markdown("<h2><i class=\'bi bi-graph-down\'></i> Zona de Descenso Histórica</h2>", unsafe_allow_html=True)'),
    ('st.header("📊 Estudio LaLiga")', 'st.markdown("<h2><i class=\'bi bi-bar-chart-line\'></i> Estudio LaLiga</h2>", unsafe_allow_html=True)'),
    
    ('st.markdown("### 🌟 Virtudes")', 'st.markdown("### <i class=\'bi bi-star\'></i> Virtudes", unsafe_allow_html=True)'),
    ('st.markdown("### ⚠️ Problemas Detectados")', 'st.markdown("### <i class=\'bi bi-exclamation-triangle\'></i> Problemas Detectados", unsafe_allow_html=True)'),
    ('st.markdown("### 📈 Estadísticas Detalladas")', 'st.markdown("### <i class=\'bi bi-graph-up\'></i> Estadísticas Detalladas", unsafe_allow_html=True)'),
    ('st.subheader("Estudio Global de Equipos")', 'st.markdown("<h3><i class=\'bi bi-globe\'></i> Estudio Global de Equipos</h3>", unsafe_allow_html=True)'),
    ('st.subheader("Comparativa de Temporadas: 1ª Vuelta vs 2ª Vuelta")', 'st.markdown("<h3><i class=\'bi bi-arrow-left-right\'></i> Comparativa de Temporadas: 1ª Vuelta vs 2ª Vuelta</h3>", unsafe_allow_html=True)'),
    ('st.subheader("📈 Progresión Histórica por Jornada")', 'st.markdown("<h3><i class=\'bi bi-graph-up-arrow\'></i> Progresión Histórica por Jornada</h3>", unsafe_allow_html=True)'),
    ('st.subheader("📊 Comparativa de Puntos por Temporada")', 'st.markdown("<h3><i class=\'bi bi-bar-chart-line\'></i> Comparativa de Puntos por Temporada</h3>", unsafe_allow_html=True)'),
    ('st.subheader("🔬 Comparativa Avanzada: Puntos y Posición")', 'st.markdown("<h3><i class=\'bi bi-search\'></i> Comparativa Avanzada: Puntos y Posición</h3>", unsafe_allow_html=True)'),
    ('st.markdown("#### ⚽ Progresión de Puntos")', 'st.markdown("#### <i class=\'bi bi-dribbble\'></i> Progresión de Puntos", unsafe_allow_html=True)'),
    ('st.markdown("#### 📉 Progresión de Posición")', 'st.markdown("#### <i class=\'bi bi-graph-down-arrow\'></i> Progresión de Posición", unsafe_allow_html=True)'),
    ('st.header("📈 Progresión de Jugadores")', 'st.markdown("<h2><i class=\'bi bi-person-lines-fill\'></i> Progresión de Jugadores</h2>", unsafe_allow_html=True)'),
    ('st.subheader(f"Evolución de {selected_player}")', 'st.markdown(f"<h3><i class=\'bi bi-graph-up\'></i> Evolución de {selected_player}</h3>", unsafe_allow_html=True)'),
    ('st.subheader("👯 Buscar Jugadores Similares (Top 20)")', 'st.markdown("<h3><i class=\'bi bi-people\'></i> Buscar Jugadores Similares (Top 20)</h3>", unsafe_allow_html=True)'),
    
    # Selectboxes without Emojis
    ('st.selectbox("📅 Selecciona Temporada:"', 'st.selectbox("Selecciona Temporada:"'),
    ('st.selectbox("🏠 Equipo Local:"', 'st.selectbox("Equipo Local:"'),
    ('st.selectbox("✈️ Equipo Visitante:"', 'st.selectbox("Equipo Visitante:"'),
    ('st.text_input("🔑 Introduce tu API Key', 'st.text_input("Introduce tu API Key'),

    # Buttons
    ('st.button("👥 Lineups"', 'st.button("Lineups", icon=":material/groups:"'),
    ('st.button("🎯 Shotmaps"', 'st.button("Shotmaps", icon=":material/my_location:"'),
    ('st.button("📈 Statistics"', 'st.button("Statistics", icon=":material/bar_chart:"'),
    ('st.button("➕ Añadir Comparativa")', 'st.button("Añadir Comparativa", icon=":material/add:")'),
    ('st.button("🗑️ Limpiar Todo", type="secondary")', 'st.button("Limpiar Todo", icon=":material/delete:", type="secondary")'),
    ('st.button("🔍 Buscar Gemelos")', 'st.button("Buscar Gemelos", icon=":material/search:")'),

    # Downloads
    ('label="📥 Descargar Histórico Completo (Excel)",', 'label="Descargar Histórico Completo (Excel)", icon=":material/download:",'),
    ('label=f"📥 Descargar Datos {season}",', 'label=f"Descargar Datos {season}", icon=":material/download:",'),

    # Expanders
    ('st.expander("🔎 Ver Datos de Proyección")', 'st.expander("Ver Datos de Proyección", icon=":material/search:")'),

    # Info
    ('st.info("👆 Añade equipos arriba para comenzar la comparativa.")', 'st.info("Añade equipos arriba para comenzar la comparativa.", icon=":material/info:")')
]

for old, new in replacements:
    code = code.replace(old, new)

with codecs.open(filepath, 'w', 'utf-8') as f:
    f.write(code)

print("Replacement complete.")
