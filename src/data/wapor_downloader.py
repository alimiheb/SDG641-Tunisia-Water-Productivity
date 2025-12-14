"""
Module pour télécharger les données WaPOR v3 via l'API REST
Basé sur: https://wapor.apps.fao.org/
"""

import os
import yaml
import requests
from datetime import datetime
from tqdm import tqdm
import numpy as np
import rasterio
from rasterio.windows import from_bounds

try:
    from osgeo import gdal
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False
    print("ℹ️  GDAL non disponible - utilisation de rasterio pour le découpage")

class WaPORDownloader:
    """
    Classe pour télécharger les données WaPOR pour la Tunisie
    """
    
    def __init__(self, config_path='config/config.yaml'):
        """
        Initialise le downloader avec la configuration
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # WaPOR v3 API
        self.base_url = "https://data.apps.fao.org/gismgr/api/v2/catalog/workspaces/WAPOR-3/mapsets"
        self.bbox = self.config['area_of_interest']['bbox']
        self.years = self.config['temporal']['years']
        self.output_dir = 'data/raw'
        
        # Créer les dossiers de sortie
        os.makedirs(self.output_dir, exist_ok=True)
        
        print(f"✓ WaPOR v3 Downloader initialisé")
        print(f"  API: {self.base_url}")
        print(f"  Période: {self.years[0]}-{self.years[-1]}")
        print(f"  Zone: Tunisia (bbox: {self.bbox})")
    
    def connect_api(self):
        """
        Se connecter à l'API WaPOR v3
        """
        try:
            response = requests.get(self.base_url, timeout=10)
            response.raise_for_status()
            print(f"✓ Connexion à l'API WaPOR v3 réussie")
            return True
        except Exception as e:
            print(f"✗ Erreur de connexion: {e}")
            print(f"ℹ️  Vérifiez votre connexion internet")
            return False
    
    def collect_responses(self, url, info=["code"]):
        """
        Collecte les réponses paginées de l'API WaPOR
        (Fonction officielle du notebook WaPOR)
        """
        data = {"links": [{"rel": "next", "href": url}]}
        output = list()
        while "next" in [x["rel"] for x in data["links"]]:
            url_ = [x["href"] for x in data["links"] if x["rel"] == "next"][0]
            response = requests.get(url_)
            response.raise_for_status()
            data = response.json()["response"]
            if isinstance(info, list):
                output += [tuple(x.get(y) for y in info) for x in data["items"]]
            else:
                output += data["items"]
        if isinstance(info, list):
            output = sorted(output)
        return output
    
    def list_available_mapsets(self):
        """
        Liste tous les mapsets (ensembles de données) disponibles
        """
        try:
            all_mapsets = self.collect_responses(self.base_url, info=["code", "caption"])
            print("\n📋 Mapsets WaPOR v3 disponibles:")
            for code, caption in all_mapsets[:20]:  # Afficher les 20 premiers
                print(f"  - {code}: {caption}")
            return all_mapsets
        except Exception as e:
            print(f"✗ Erreur: {e}")
            return []
    
    def get_rasters_for_mapset(self, mapset_code):
        """
        Récupère tous les rasters d'un mapset spécifique
        """
        try:
            mapset_url = f"{self.base_url}/{mapset_code}/rasters"
            all_rasters = self.collect_responses(mapset_url, info=["code", "downloadUrl"])
            return all_rasters
        except Exception as e:
            print(f"✗ Erreur: {e}")
            return []
    
    def download_raster(self, tif_url, output_filepath, bbox=None, use_gdal=True):
        """
        Télécharge un raster WaPOR pour une zone géographique spécifique
        
        Args:
            tif_url: URL du GeoTIFF
            output_filepath: Chemin de sortie
            bbox: Bounding box [left, top, right, bottom] ou None pour bbox du config
            use_gdal: Si True et GDAL disponible, découpe le raster
        """
        if bbox is None:
            # Tunisia bbox: [lon_min, lat_min, lon_max, lat_max]
            bbox_config = self.bbox
            bbox = [bbox_config[0], bbox_config[3], bbox_config[2], bbox_config[1]]  # [left, top, right, bottom]
        
        try:
            # Méthode 1: GDAL (découpage COG - le plus efficace)
            if use_gdal and GDAL_AVAILABLE:
                translate_options = gdal.TranslateOptions(
                    projWin=bbox,
                    bandList=[1],
                    unscale=True
                )
                
                ds = gdal.Translate(output_filepath, f"/vsicurl/{tif_url}", options=translate_options)
                
                if ds is not None:
                    print(f"  ✓ Téléchargé et découpé: {output_filepath}")
                    ds = None
                    return output_filepath
                else:
                    print(f"  ✗ Échec GDAL, tentative avec rasterio...")
            
            # Méthode 2: Rasterio (découpage COG - alternatif sans GDAL)
            print(f"  📥 Téléchargement et découpage avec rasterio...")
            
            with rasterio.open(tif_url) as src:
                # Convertir bbox en coordonnées pixel
                window = from_bounds(bbox[0], bbox[3], bbox[2], bbox[1], src.transform)
                
                # Lire seulement la fenêtre qui nous intéresse
                data = src.read(1, window=window)
                
                # Calculer la nouvelle transformation
                window_transform = src.window_transform(window)
                
                # Sauvegarder le sous-ensemble
                profile = src.profile.copy()
                profile.update({
                    'height': window.height,
                    'width': window.width,
                    'transform': window_transform
                })
                
                with rasterio.open(output_filepath, 'w', **profile) as dst:
                    dst.write(data, 1)
            
            print(f"  ✓ Téléchargé et découpé: {output_filepath}")
            return output_filepath
                
        except Exception as e:
            print(f"  ✗ Erreur: {e}")
            return None
    
    def download_annual_et(self, years=None, level=2):
        """
        Télécharge l'évapotranspiration annuelle (AETI) pour la Tunisie
        
        Args:
            years: Liste des années (par défaut: config)
            level: Niveau WaPOR (1 ou 2, défaut=2 pour 100m résolution)
        """
        if years is None:
            years = self.years
        
        print(f"\n📥 Téléchargement: Évapotranspiration annuelle (Level {level})")
        
        # Mapset code pour ET annuel
        mapset_code = f"L{level}-AETI-A"
        
        # Créer le dossier de sortie
        output_dir = f"{self.output_dir}/ET"
        os.makedirs(output_dir, exist_ok=True)
        
        # Récupérer tous les rasters disponibles
        all_rasters = self.get_rasters_for_mapset(mapset_code)
        
        if not all_rasters:
            print(f"  ✗ Aucun raster trouvé pour {mapset_code}")
            return []
        
        downloaded_files = []
        for year in years:
            # Trouver le raster pour cette année
            year_rasters = [r for r in all_rasters if str(year) in r[0]]
            
            if year_rasters:
                code, url = year_rasters[0]
                output_file = f"{output_dir}/AETI_L{level}_{year}.tif"
                
                if os.path.exists(output_file):
                    print(f"  ⊙ {year}: existe déjà")
                    downloaded_files.append(output_file)
                else:
                    print(f"  📥 {year}: téléchargement en cours...")
                    result = self.download_raster(url, output_file)
                    if result:
                        downloaded_files.append(result)
            else:
                print(f"  ✗ {year}: données non disponibles")
        
        return downloaded_files
    
    def download_transpiration(self, years=None, level=2):
        """
        Télécharge la transpiration annuelle (TBP) pour la Tunisie
        """
        if years is None:
            years = self.years
        
        print(f"\n📥 Téléchargement: Transpiration annuelle (Level {level})")
        
        mapset_code = f"L{level}-T-A"
        output_dir = f"{self.output_dir}/TBP"
        os.makedirs(output_dir, exist_ok=True)
        
        all_rasters = self.get_rasters_for_mapset(mapset_code)
        
        if not all_rasters:
            print(f"  ✗ Aucun raster trouvé pour {mapset_code}")
            return []
        
        downloaded_files = []
        for year in years:
            year_rasters = [r for r in all_rasters if str(year) in r[0]]
            
            if year_rasters:
                code, url = year_rasters[0]
                output_file = f"{output_dir}/TBP_L{level}_{year}.tif"
                
                if os.path.exists(output_file):
                    print(f"  ⊙ {year}: existe déjà")
                    downloaded_files.append(output_file)
                else:
                    print(f"  📥 {year}: téléchargement en cours...")
                    result = self.download_raster(url, output_file)
                    if result:
                        downloaded_files.append(result)
            else:
                print(f"  ✗ {year}: données non disponibles")
        
        return downloaded_files
    
    def download_precipitation(self, years=None, level=1):
        """
        Télécharge les précipitations annuelles (PCP) pour la Tunisie
        """
        if years is None:
            years = self.years
        
        print(f"\n📥 Téléchargement: Précipitations annuelles (Level {level})")
        
        mapset_code = f"L{level}-PCP-A"
        output_dir = f"{self.output_dir}/PCP"
        os.makedirs(output_dir, exist_ok=True)
        
        all_rasters = self.get_rasters_for_mapset(mapset_code)
        
        if not all_rasters:
            print(f"  ✗ Aucun raster trouvé pour {mapset_code}")
            return []
        
        downloaded_files = []
        for year in years:
            year_rasters = [r for r in all_rasters if str(year) in r[0]]
            
            if year_rasters:
                code, url = year_rasters[0]
                output_file = f"{output_dir}/PCP_L{level}_{year}.tif"
                
                if os.path.exists(output_file):
                    print(f"  ⊙ {year}: existe déjà")
                    downloaded_files.append(output_file)
                else:
                    print(f"  📥 {year}: téléchargement en cours...")
                    result = self.download_raster(url, output_file)
                    if result:
                        downloaded_files.append(result)
            else:
                print(f"  ✗ {year}: données non disponibles")
        
        return downloaded_files
    
    def download_land_cover(self, years=None, level=1):
        """
        Télécharge la couverture du sol (LCC - Land Cover Classification) pour la Tunisie
        """
        if years is None:
            years = self.years
        
        print(f"\n📥 Téléchargement: Couverture du sol (Level {level})")
        
        mapset_code = f"L{level}-LCC-A"
        output_dir = f"{self.output_dir}/LCC"
        os.makedirs(output_dir, exist_ok=True)
        
        all_rasters = self.get_rasters_for_mapset(mapset_code)
        
        if not all_rasters:
            print(f"  ✗ Aucun raster trouvé pour {mapset_code}")
            return []
        
        downloaded_files = []
        for year in years:
            year_rasters = [r for r in all_rasters if str(year) in r[0]]
            
            if year_rasters:
                code, url = year_rasters[0]
                output_file = f"{output_dir}/LCC_L{level}_{year}.tif"
                
                if os.path.exists(output_file):
                    print(f"  ⊙ {year}: existe déjà")
                    downloaded_files.append(output_file)
                else:
                    print(f"  📥 {year}: téléchargement en cours...")
                    result = self.download_raster(url, output_file)
                    if result:
                        downloaded_files.append(result)
            else:
                print(f"  ✗ {year}: données non disponibles")
        
        return downloaded_files