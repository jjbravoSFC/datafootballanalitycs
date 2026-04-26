import pandas as pd
import os

excel_file = 'Temporadas Clasificaciones.xlsx'

try:
    print(f"Reading {excel_file}...")
    xl = pd.ExcelFile(excel_file)
    
    for sheet_name in xl.sheet_names:
        # Expected naming convention: Temporadas Clasificaciones.xlsx - [AAAA-AAAA].csv
        # The sheet name is likely '1999-2000', etc.
        output_dir = os.path.join("CSVs", "TemporadasClasificaciones")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = os.path.join(output_dir, f"Temporadas Clasificaciones.xlsx - [{sheet_name}].csv")
        
        print(f"Processing sheet: {sheet_name} -> {output_filename}")
        
        df = xl.parse(sheet_name)
        
        # Basic cleanup just in case, though app handles it too
        df.to_csv(output_filename, index=False, encoding='utf-8')
        
    print("Conversion complete.")

except Exception as e:
    print(f"Error: {e}")
