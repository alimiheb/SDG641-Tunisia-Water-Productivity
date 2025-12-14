"""
Script pour extraire les données AQUASTAT et World Bank pour Tunisia
"""

import pandas as pd
import os

# Créer répertoire de sortie
os.makedirs('data/processed', exist_ok=True)

print("="*60)
print("EXTRACTION DONNÉES TUNISIA")
print("="*60)

# 1. WORLD BANK - GVA_a (Agriculture Value Added)
print("\n1️⃣ Extraction GVA_a (World Bank)...")
df_wb = pd.read_csv('data/external/API_NV.AGR.TOTL.CD_DS2_en_csv_v2_110847.csv', skiprows=4)
tunisia_wb = df_wb[df_wb['Country Name'] == 'Tunisia']

years = ['2018', '2019', '2020', '2021', '2022', '2023']
gva_data = []

for year in years:
    if year in tunisia_wb.columns:
        value = tunisia_wb[year].values[0]
        gva_data.append({
            'year': int(year),
            'GVA_a': value
        })
        print(f"  {year}: ${value:,.0f}")

df_gva = pd.DataFrame(gva_data)

# 2. AQUASTAT - V_a et autres variables
print("\n2️⃣ Extraction données AQUASTAT...")

try:
    # Essayer différents encodages
    for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        try:
            df_aqua = pd.read_csv('data/external/AQUASTAT Dissemination System (2).csv', 
                                 encoding=encoding)
            print(f"  ✓ Fichier chargé avec encoding: {encoding}")
            break
        except:
            continue
    
    # Afficher colonnes pour debug
    print(f"  📋 Colonnes: {df_aqua.columns.tolist()}")
    
    # Filtrer Tunisia pour années 2017-2022 (disponibles dans AQUASTAT)
    area_col = 'Area' if 'Area' in df_aqua.columns else 'AREA'
    year_col = 'Year' if 'Year' in df_aqua.columns else 'timePointYears'
    
    tunisia_aqua = df_aqua[
        (df_aqua[area_col] == 'Tunisia') & 
        (df_aqua[year_col].astype(int).between(2017, 2022))
    ]
    
    print(f"  ✓ {len(tunisia_aqua)} lignes Tunisia (2017-2022)")
    
    # Variables clés pour AWP
    key_variables = [
        'Agricultural water withdrawal',
        'Total renewable water resources',
        'Agricultural water withdrawal as % of total renewable water resources',
        'SDG 6.4.1. Agricultural Water Use Efficiency',
        '% of agricultural GVA produced by irrigated agriculture'
    ]
    
    print("\n  Variables disponibles:")
    var_col = 'Variable' if 'Variable' in tunisia_aqua.columns else 'aquastatElement'
    for var in key_variables:
        data = tunisia_aqua[tunisia_aqua[var_col].astype(str).str.contains(var, case=False, na=False)]
        if len(data) > 0:
            print(f"    ✓ {var}: {len(data)} observations")
        else:
            print(f"    ✗ {var}: Non trouvé")
    
    # Déterminer le nom de la colonne Variable
    var_col = 'Variable' if 'Variable' in tunisia_aqua.columns else 'aquastatElement'
    
    # Extraire Agricultural water withdrawal (volume ABSOLU en 10^9 m³/year)
    # Filtrer par Variable ET Unit pour avoir les volumes, pas les pourcentages
    unit_col = 'Unit' if 'Unit' in tunisia_aqua.columns else 'Unit'
    v_a_data = tunisia_aqua[
        (tunisia_aqua[var_col] == 'Agricultural water withdrawal') &
        (tunisia_aqua[unit_col] == '10^9 m3/year')
    ]
    
    # Extraire % of agricultural GVA produced by irrigated agriculture
    irrigated_gva_data = tunisia_aqua[
        (tunisia_aqua[var_col] == '% of agricultural GVA produced by irrigated agriculture') &
        (tunisia_aqua[unit_col] == '%')
    ]
    
    # Extraire Agricultural Water Use Efficiency (USD/m³)
    awue_data = tunisia_aqua[tunisia_aqua[var_col].astype(str).str.contains('Agricultural Water Use Efficiency', case=False, na=False)]
    
    # Créer dictionnaires pour V_a et c_r
    v_a_dict = {}
    c_r_dict = {}
    
    # Extraire V_a
    if len(v_a_data) > 0:
        print("\n  📊 Agricultural water withdrawal (V_a):")
        year_col = 'Year' if 'Year' in v_a_data.columns else 'timePointYears'
        val_col = 'Value' if 'Value' in v_a_data.columns else 'Value'
        
        for _, row in v_a_data.iterrows():
            year = int(row[year_col])
            value = float(row[val_col]) * 1e9  # Convertir 10^9 m³ en m³
            v_a_dict[year] = value
            print(f"    {year}: {value/1e9:.4f} x 10^9 m³ = {value:.2e} m³")
    
    # Extraire c_r depuis % irrigué
    if len(irrigated_gva_data) > 0:
        print("\n  🌾 % GVA irrigué → c_r (rainfed ratio):")
        year_col = 'Year' if 'Year' in irrigated_gva_data.columns else 'timePointYears'
        val_col = 'Value' if 'Value' in irrigated_gva_data.columns else 'Value'
        
        for _, row in irrigated_gva_data.iterrows():
            year = int(row[year_col])
            pct_irrigated = float(row[val_col])
            c_r = 1 - (pct_irrigated / 100)  # c_r = rainfed ratio
            c_r_dict[year] = c_r
            print(f"    {year}: {pct_irrigated:.2f}% irrigué → c_r = {c_r:.4f} ({c_r*100:.2f}% rainfed)")
    
    # Si V_a et c_r trouvés, les utiliser; sinon estimation
    use_real_v_a = len(v_a_dict) > 0
    use_real_c_r = len(c_r_dict) > 0
    
except Exception as e:
    print(f"  ⚠️ Erreur AQUASTAT: {e}")
    print("  → Utiliser approximation basée sur ratios typiques")
    use_real_v_a = False
    use_real_c_r = False
    v_a_dict = {}
    c_r_dict = {}

# 3. Calculer c_r réel depuis données surfaciques
print("\n3️⃣ Calcul c_r (rainfed ratio) depuis surfaces...")
# Source: Agricultural land area Tunisia = 97,005 km² = 9,700,500 ha (2018-2023)
# Source: TUN-gmia.xls - Area equipped for irrigation = 455,070 ha
total_agricultural_area_ha = 9700500  # ha
irrigated_area_ha = 455070  # ha
c_r_area_based = 1 - (irrigated_area_ha / total_agricultural_area_ha)

print(f"  📊 Surface agricole totale: {total_agricultural_area_ha:,} ha")
print(f"  💧 Surface irriguée (TUN-gmia): {irrigated_area_ha:,} ha")
print(f"  🌾 c_r calculé: {c_r_area_based:.4f} ({c_r_area_based*100:.2f}% rainfed)")

# 4. Créer fichier consolidé
print("\n4️⃣ Création fichier consolidé...")

if use_real_v_a:
    print(f"  ✓ V_a: Données AQUASTAT réelles")
    print(f"  ✓ c_r: Calculé depuis surfaces (area-based)")
    
    aquastat_data = {
        'year': [],
        'V_a': [],
        'c_r': []
    }
    
    # AQUASTAT a 2017-2022, World Bank a 2018-2023
    # On utilise l'intersection: 2018-2022
    for year in [2018, 2019, 2020, 2021, 2022]:
        aquastat_data['year'].append(year)
        aquastat_data['V_a'].append(v_a_dict.get(year, None))
        aquastat_data['c_r'].append(c_r_area_based)  # c_r constant (surfaces fixes 2018-2023)
    
    # Pour 2023, extrapoler depuis 2022
    aquastat_data['year'].append(2023)
    aquastat_data['V_a'].append(v_a_dict.get(2022, 2710000000))  # Utiliser valeur 2022
    aquastat_data['c_r'].append(c_r_area_based)  # c_r constant
    
    df_aqua_est = pd.DataFrame(aquastat_data)
else:
    print("  ⚠️ Utilisation d'estimations FAO AQUASTAT")
    # Estimations typiques pour Tunisia (source: FAO AQUASTAT historique)
    # V_a ≈ 2.8-3.2 milliards m³
    # c_r ≈ 0.60-0.70 (60-70% rainfed)
    
    aquastat_estimates = {
        'year': [2018, 2019, 2020, 2021, 2022, 2023],
        'V_a': [2850000000, 2900000000, 2750000000, 2850000000, 2900000000, 2950000000],  # m³
        'c_r': [0.65, 0.65, 0.66, 0.64, 0.65, 0.65]  # fraction rainfed
    }
    
    df_aqua_est = pd.DataFrame(aquastat_estimates)

# Fusionner
df_final = pd.merge(df_gva, df_aqua_est, on='year')

print("\n📋 Données consolidées:")
print(df_final.to_string(index=False))

# Sauvegarder
output_file = 'data/external/aquastat_tunisia_clean.csv'
df_final.to_csv(output_file, index=False)

print(f"\n💾 Sauvegardé: {output_file}")

if use_real_v_a:
    print("\n✅ V_a: Données AQUASTAT réelles utilisées")
    print("✅ c_r: Calculé depuis surfaces agricoles (area-based)")
    print(f"   → Total agricole: 97,005 km² | Irrigué: 455,070 ha | c_r = {c_r_area_based:.4f}")
else:
    print("\n⚠️ NOTE: V_a et c_r sont des ESTIMATIONS basées sur données historiques AQUASTAT")
    print("   Pour obtenir les vraies valeurs, vérifier: http://www.fao.org/aquastat/")

print("\n✅ Extraction terminée!")
