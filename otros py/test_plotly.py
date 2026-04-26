import plotly.graph_objects as go
import base64
import os

img_path = r"c:\OneDrive\OneDrive\Desarrollos Locales\Temporadas Clasificaciones\Imagenes\Escudos\LaLiga 1\2025-2026\realmadrid.png"
if os.path.exists(img_path):
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        src = f"data:image/png;base64,{img_b64}"
        
    fig = go.Figure(data=[go.Table(
        header=dict(values=['Team', 'Logo']),
        cells=dict(values=[
            ['Real Madrid'],
            [f'<img src="{src}" height="30">']
        ])
    )])
    fig.write_html("test_table.html")
    print("Test HTML generated.")
else:
    print(f"Image not found: {img_path}")
