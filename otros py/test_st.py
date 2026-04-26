import streamlit as st
import streamlit.components.v1 as components

st.title("Test download html2canvas")

html_code = """
<html>
<head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<style>
    body { font-family: sans-serif; }
    table { border-collapse: collapse; width: 100%; color: white; background-color: #1e293b; }
    th { background-color: #334155; padding: 8px; border: 1px solid #475569; }
    td { padding: 8px; border: 1px solid #475569; text-align: center; }
    button { padding: 10px; margin-bottom: 15px; cursor: pointer; background-color: #38bdf8; border: none; font-weight: bold; border-radius: 5px; }
</style>
</head>
<body>
    <button onclick="download()">Descargar como Imagen</button>
    <div id="capture">
        <table>
            <tr><th>Equipo</th><th>PG</th><th>PE</th></tr>
            <tr>
                <td><img src="https://via.placeholder.com/30" height="30"> Real Madrid</td>
                <td>10</td><td>2</td>
            </tr>
            <tr>
                <td><img src="https://via.placeholder.com/30" height="30"> Barcelona</td>
                <td>9</td><td>3</td>
            </tr>
        </table>
    </div>
    
    <script>
    function download() {
        html2canvas(document.querySelector("#capture"), {backgroundColor: '#1e293b'}).then(canvas => {
            let link = document.createElement('a');
            link.download = 'test_table.png';
            link.href = canvas.toDataURL();
            link.click();
        });
    }
    </script>
</body>
</html>
"""

components.html(html_code, height=400)
