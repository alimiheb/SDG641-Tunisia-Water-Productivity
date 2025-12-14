"""
Module pour télécharger les données ESA WorldCover
Alternative pour la couverture du sol (Land Cover Classification)
Source: https://esa-worldcover.org/
"""

import os
import yaml
import requests
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
from shapely.geometry import box
import numpy as np

class ESAWorldCoverDownloader:
    """
    Télécharge les données de couverture du sol depuis ESA WorldCover
    - 2020: 10m résolution
    - 2021: 10m résolution
    """
    
    def __init__(self, config_path='config/config.yaml'):
        """
        Initialise le downloader ESA WorldCover
        """
        # Construire le chemin absolu vers le répertoire du projet
        if os.path.isabs(config_path):
            config_file = config_path
        else:
            # Remonter depuis src/data/ vers la racine du projet
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_file = os.path.join(project_root, config_path)
        
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # ESA WorldCover est disponible via AWS S3
        self.base_url = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
        self.bbox = self.config['area_of_interest']['bbox']
        
        # Utiliser un chemin absolu pour output_dir
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.output_dir = os.path.join(project_root, 'data', 'raw')
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        print(f"✓ ESA WorldCover Downloader initialisé")
        print(f"  Source: ESA WorldCover (10m résolution)")
        print(f"  Années disponibles: 2020, 2021")
        print(f"  Zone: Tunisia (bbox: {self.bbox})")
    
    def get_tiles_for_bbox(self):
        """
        Identifier les tuiles ESA WorldCover qui couvrent la Tunisie
        ESA WorldCover utilise une grille 3°x3°
        """
        # Tuiles qui couvrent la Tunisie (longitude 7.5-11.6, latitude 30-37.5)
        # Format: N{lat}E{lon} ou N{lat}W{lon}
        tiles = [
            "N30E006",  # Sud-Ouest
            "N30E009",  # Sud-Centre
            "N33E006",  # Centre-Ouest
            "N33E009",  # Centre
            "N36E006",  # Nord-Ouest
            "N36E009",  # Nord-Centre
        ]
        
        return tiles
    
    def download_tile(self, tile_name, year=2020):
        """
        Télécharger une tuile ESA WorldCover
        """
        # URL format: version/year/map/ESA_WorldCover_10m_year_version_tile.tif
        version = "v100" if year == 2020 else "v200"
        
        url = f"{self.base_url}/{version}/{year}/map/ESA_WorldCover_10m_{year}_{version}_{tile_name}_Map.tif"
        
        output_dir = f"{self.output_dir}/LCC/tiles"
        os.makedirs(output_dir, exist_ok=True)
        output_file = f"{output_dir}/WorldCover_{year}_{tile_name}.tif"
        
        if os.path.exists(output_file):
            return output_file
        
        print(f"  📥 {tile_name}...", end=" ")
        
        try:
            # Télécharger avec streaming (fichiers volumineux)
            response = requests.get(url, timeout=300, stream=True)
            
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                
                with open(output_file, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                
                size_mb = os.path.getsize(output_file) / (1024 * 1024)
                print(f"✓ ({size_mb:.0f}MB)")
                return output_file
            else:
                print(f"✗ (Erreur {response.status_code})")
                return None
                
        except Exception as e:
            print(f"✗ ({str(e)[:50]})")
            return None
    
    def download_and_crop_land_cover(self, year=2020):
        """
        Télécharger et fusionner les tuiles pour la Tunisie
        """
        print(f"\n📥 Téléchargement: ESA WorldCover {year}")
        print(f"ℹ️  Résolution: 10m (haute résolution)")
        print(f"ℹ️  Classes: 11 types de couverture du sol")
        
        output_dir = f"{self.output_dir}/LCC"
        os.makedirs(output_dir, exist_ok=True)
        output_file = f"{output_dir}/LCC_ESA_{year}.tif"
        
        if os.path.exists(output_file):
            print(f"✓ Fichier existe déjà: {output_file}")
            return output_file
        
        # Télécharger les tuiles
        tiles = self.get_tiles_for_bbox()
        print(f"\n📦 Téléchargement de {len(tiles)} tuiles...")
        
        tile_files = []
        for tile in tiles:
            tile_file = self.download_tile(tile, year)
            if tile_file and os.path.exists(tile_file):
                tile_files.append(tile_file)
        
        if not tile_files:
            print("✗ Aucune tuile téléchargée")
            return None
        
        print(f"\n🔗 Découpage des tuiles à la bbox Tunisie...")
        
        try:
            # Approche optimisée: découper chaque tuile puis fusionner
            cropped_tiles = []
            temp_dir = f"{self.output_dir}/LCC/temp"
            os.makedirs(temp_dir, exist_ok=True)
            
            for i, tile_file in enumerate(tile_files):
                print(f"  📐 Découpage tuile {i+1}/{len(tile_files)}...", end=" ")
                
                try:
                    with rasterio.open(tile_file) as src:
                        # Vérifier si la tuile intersecte la bbox
                        tile_bounds = src.bounds
                        
                        # Intersection bbox
                        intersects = not (
                            tile_bounds.right < self.bbox[0] or
                            tile_bounds.left > self.bbox[2] or
                            tile_bounds.top < self.bbox[1] or
                            tile_bounds.bottom > self.bbox[3]
                        )
                        
                        if not intersects:
                            print("✗ (hors zone)")
                            continue
                        
                        # Calculer la fenêtre d'intersection
                        try:
                            from rasterio.windows import from_bounds
                            
                            # Calculer la fenêtre pour la bbox (en coordonnées géographiques)
                            window = from_bounds(
                                self.bbox[0],  # left (lon_min)
                                self.bbox[1],  # bottom (lat_min)
                                self.bbox[2],  # right (lon_max)
                                self.bbox[3],  # top (lat_max)
                                src.transform
                            )
                            
                            # Lire la fenêtre
                            out_image = src.read(window=window)
                            out_transform = src.window_transform(window)
                            
                            # Vérifier si les données sont valides
                            if out_image.size == 0:
                                print("✗ (fenêtre vide)")
                                continue
                            
                            # Sauvegarder le découpage
                            temp_file = f"{temp_dir}/cropped_{i}.tif"
                            profile = src.profile.copy()
                            profile.update({
                                'height': out_image.shape[1] if out_image.ndim == 3 else out_image.shape[0],
                                'width': out_image.shape[2] if out_image.ndim == 3 else out_image.shape[1],
                                'transform': out_transform,
                                'compress': 'lzw'
                            })
                            
                            with rasterio.open(temp_file, 'w', **profile) as dst:
                                dst.write(out_image)
                            
                            size_mb = os.path.getsize(temp_file) / (1024**2)
                            cropped_tiles.append(temp_file)
                            print(f"✓ ({size_mb:.1f}MB)")
                            
                        except ValueError:
                            print("✗ (hors bbox)")
                            continue
                            
                except Exception as e:
                    print(f"✗ ({str(e)[:30]})")
                    continue
            
            if not cropped_tiles:
                print("✗ Aucune tuile découpée")
                return None
            
            # Si une seule tuile, copier directement
            if len(cropped_tiles) == 1:
                print(f"\n📋 Une seule tuile, copie directe...")
                import shutil
                shutil.copy2(cropped_tiles[0], output_file)
            else:
                print(f"\n🔗 Fusion de {len(cropped_tiles)} tuiles...")
                
                # Méthode robuste: construire mosaïque manuellement
                try:
                    # Ouvrir toutes les tuiles
                    src_files = [rasterio.open(f) for f in cropped_tiles]
                    
                    # Calculer l'étendue globale
                    min_x = min(src.bounds.left for src in src_files)
                    max_x = max(src.bounds.right for src in src_files)
                    min_y = min(src.bounds.bottom for src in src_files)
                    max_y = max(src.bounds.top for src in src_files)
                    
                    # Utiliser la résolution de la première tuile
                    res_x, res_y = src_files[0].res
                    width = int((max_x - min_x) / res_x)
                    height = int((max_y - min_y) / abs(res_y))
                    
                    transform = rasterio.transform.from_bounds(min_x, min_y, max_x, max_y, width, height)
                    
                    # Créer le fichier de sortie
                    profile = src_files[0].profile.copy()
                    profile.update({
                        'width': width,
                        'height': height,
                        'transform': transform,
                        'compress': 'lzw'
                    })
                    
                    print(f"  📏 Mosaïque: {width}x{height} pixels")
                    
                    # Écrire tuile par tuile
                    with rasterio.open(output_file, 'w', **profile) as dst:
                        # Initialiser avec zéro
                        dst.write(np.zeros((height, width), dtype=profile['dtype']), 1)
                        
                        # Copier chaque tuile
                        for i, src in enumerate(src_files):
                            print(f"  ✍️ Tuile {i+1}/{len(src_files)}...", end=" ")
                            
                            # Lire les données
                            data = src.read(1)
                            
                            # Calculer la fenêtre dans le fichier de sortie
                            src_window = rasterio.windows.from_bounds(*src.bounds, dst.transform)
                            
                            # Écrire dans la fenêtre
                            dst.write(data, 1, window=src_window)
                            print("✓")
                    
                    # Fermer
                    for src in src_files:
                        src.close()
                    
                except Exception as e:
                    print(f"  ✗ Erreur: {str(e)[:50]}")
                    for src in src_files:
                        try:
                            src.close()
                        except:
                            pass
                    return None
            
            # Nettoyer les fichiers temporaires
            for temp_file in cropped_tiles:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
            
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"✓ Fichier créé: {output_file} ({size_mb:.1f} MB)")
            
            return output_file
            
        except Exception as e:
            print(f"✗ Erreur: {e}")
            # Nettoyer
            if 'temp_dir' in locals() and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            return None
    
    def get_legend(self):
        """
        Retourne la légende des classes ESA WorldCover
        """
        legend = {
            10: "Arbre",
            20: "Arbustes",
            30: "Herbacées",
            40: "Terres cultivées",
            50: "Zones bâties",
            60: "Végétation clairsemée",
            70: "Neige et glace",
            80: "Eau permanente",
            90: "Zones humides herbacées",
            95: "Mangroves",
            100: "Mousses et lichens"
        }
        return legend
