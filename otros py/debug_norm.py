import pandas as pd
import glob
def main():
    season = "2025-2026"
    match_file = f"CSVs/TemporadasPartidos/{season}.csv"
    try:
        df_m = pd.read_csv(match_file, sep=";", encoding="utf-8")
        print("Read as utf-8 successfully!")
    except UnicodeDecodeError:
        df_m = pd.read_csv(match_file, sep=";", encoding="latin1")
        print("Fallback to latin1")
    
    alaves_matches = df_m[(df_m['Local'].str.contains('Alav', case=False, na=False)) | (df_m['Visitante'].str.contains('Alav', case=False, na=False))]
    print(alaves_matches[['Local', 'Visitante']].head(2))

if __name__ == "__main__":
    main()
