"""
Module pour les analyses statistiques spatiales.
"""

import logging
from typing import Dict, List, Optional, Union
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterstats import zonal_stats
from shapely.geometry import mapping

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SpatialStats:
    """Classe pour les statistiques spatiales sur les gouvernorats tunisiens."""
    
    def __init__(self, shapefile_path: Optional[str] = None):
        """
        Initialise le calculateur de statistiques spatiales.
        
        Args:
            shapefile_path: Chemin vers le shapefile des gouvernorats (GADM)
        """
        self.shapefile_path = shapefile_path
        self.governorates = None
        
        if shapefile_path:
            self.load_governorates(shapefile_path)
        
        logger.info("SpatialStats initialisé")
    
    def load_governorates(self, shapefile_path: str) -> gpd.GeoDataFrame:
        """
        Charge le shapefile des gouvernorats tunisiens.
        
        Args:
            shapefile_path: Chemin vers gadm41_TUN_1.shp
            
        Returns:
            GeoDataFrame des gouvernorats
        """
        logger.info(f"Chargement shapefile: {shapefile_path}")
        self.governorates = gpd.read_file(shapefile_path)
        
        # Standardiser les noms de colonnes
        if 'NAME_1' in self.governorates.columns:
            self.governorates['governorate'] = self.governorates['NAME_1']
        
        logger.info(f"✓ {len(self.governorates)} gouvernorats chargés")
        return self.governorates
    
    def load_irrigation_areas(self, csv_path: str) -> pd.DataFrame:
        """
        Charge les surfaces irriguées par gouvernorat depuis TUN-gmia.
        
        Args:
            csv_path: Chemin vers TUN-gmia.xls - Tunisia.csv
            
        Returns:
            DataFrame avec governorate et area_irrigated_ha
        """
        logger.info(f"Chargement surfaces irriguées: {csv_path}")
        
        # Lire le CSV
        df = pd.read_csv(csv_path, nrows=23)  # 23 gouvernorats
        df = df[['Governorate', 'Area equipped for irrigation (ha)']].copy()
        
        # Nettoyer les données
        df.columns = ['governorate', 'area_irrigated_ha']
        df['area_irrigated_ha'] = df['area_irrigated_ha'].str.replace(' ', '').astype(float)
        
        # Standardiser les noms pour correspondre à GADM
        name_mapping = {
            'Al-Kaf': 'Le Kef',
            'Ben Arous (Tunis Sud)': 'Ben Arous',
            'Dschunduba': 'Jendouba',
            'Kairouwan': 'Kairouan',
            'Nabul': 'Nabeul',
            'Saghuan': 'Zaghouan',
            'Sidi Bu Said': 'Sidi Bouzid',
            'Susa': 'Sousse',
        }
        df['governorate'] = df['governorate'].replace(name_mapping)
        
        logger.info(f"✓ {len(df)} gouvernorats avec surfaces irriguées")
        return df
    
    def zonal_statistics_raster(
        self,
        raster_path: str,
        zones: gpd.GeoDataFrame,
        stats: List[str] = None,
        categorical: bool = False
    ) -> pd.DataFrame:
        """
        Calcule les statistiques zonales depuis un raster.
        
        Args:
            raster_path: Chemin vers le fichier raster
            zones: GeoDataFrame des zones (gouvernorats)
            stats: Liste des statistiques (mean, sum, std, etc.)
            categorical: Si True, traite comme données catégorielles
            
        Returns:
            DataFrame avec statistiques par zone
        """
        if stats is None:
            stats = ['mean', 'sum', 'std', 'min', 'max', 'count']
        
        logger.info(f"Calcul statistiques zonales: {Path(raster_path).name}")
        
        # Calculer statistiques avec rasterstats
        results = zonal_stats(
            zones,
            raster_path,
            stats=stats,
            categorical=categorical,
            nodata=-9999
        )
        
        # Convertir en DataFrame
        df_stats = pd.DataFrame(results)
        
        # Ajouter noms gouvernorats
        if 'governorate' in zones.columns:
            df_stats['governorate'] = zones['governorate'].values
        elif 'NAME_1' in zones.columns:
            df_stats['governorate'] = zones['NAME_1'].values
        
        return df_stats
    
    def aggregate_by_governorate(
        self,
        raster_path: str,
        variable_name: str = 'value'
    ) -> gpd.GeoDataFrame:
        """
        Agrège un raster par gouvernorat.
        
        Args:
            raster_path: Chemin vers le raster à agréger
            variable_name: Nom de la variable (etb, wpb, etc.)
            
        Returns:
            GeoDataFrame des gouvernorats avec statistiques
        """
        if self.governorates is None:
            raise ValueError("Shapefile des gouvernorats non chargé. Utilisez load_governorates()")
        
        logger.info(f"Agrégation par gouvernorat: {variable_name}")
        
        # Calculer statistiques zonales
        stats_df = self.zonal_statistics_raster(
            raster_path,
            self.governorates,
            stats=['mean', 'sum', 'std', 'count']
        )
        
        # Fusionner avec GeoDataFrame
        result = self.governorates.copy()
        result[f'{variable_name}_mean'] = stats_df['mean']
        result[f'{variable_name}_sum'] = stats_df['sum']
        result[f'{variable_name}_std'] = stats_df['std']
        result[f'{variable_name}_count'] = stats_df['count']
        
        return result
    
    def calculate_awp_by_governorate(
        self,
        etb_raster_path: str,
        wpb_raster_path: str,
        irrigation_areas_df: pd.DataFrame,
        gva_total: float,
        v_a_total: float,
        c_r: float = 0.9531
    ) -> gpd.GeoDataFrame:
        """
        Calcule AWP par gouvernorat.
        
        Args:
            etb_raster_path: Chemin vers raster ETb annuel
            wpb_raster_path: Chemin vers raster WPb annuel
            irrigation_areas_df: DataFrame avec surfaces irriguées par gouvernorat
            gva_total: GVA agricole total (USD)
            v_a_total: Volume eau prélevé total (m³)
            c_r: Rainfed ratio (défaut 0.9531)
            
        Returns:
            GeoDataFrame avec AWP par gouvernorat
        """
        if self.governorates is None:
            raise ValueError("Shapefile des gouvernorats non chargé")
        
        logger.info("Calcul AWP par gouvernorat")
        
        # 1. Calculer statistiques zonales ETb et WPb
        etb_stats = self.aggregate_by_governorate(etb_raster_path, 'etb')
        wpb_stats = self.aggregate_by_governorate(wpb_raster_path, 'wpb')
        
        # 2. Fusionner avec surfaces irriguées
        result = etb_stats.copy()
        result = result.merge(
            irrigation_areas_df,
            on='governorate',
            how='left'
        )
        result['wpb_mean'] = wpb_stats['wpb_mean']
        
        # 3. Calculer V_ETb par gouvernorat (ETb moyen × surface irriguée)
        result['v_etb_m3'] = result['etb_mean'] * result['area_irrigated_ha'] * 10000  # ha → m²
        
        # 4. Répartir GVA et V_a proportionnellement aux surfaces irriguées
        total_irrigated_ha = irrigation_areas_df['area_irrigated_ha'].sum()
        result['gva_irrigated'] = (
            gva_total * (1 - c_r) * 
            result['area_irrigated_ha'] / total_irrigated_ha
        )
        result['v_a_m3'] = (
            v_a_total * 
            result['area_irrigated_ha'] / total_irrigated_ha
        )
        
        # 5. Calculer AWP par gouvernorat
        result['awp_we'] = result['gva_irrigated'] / result['v_a_m3']
        result['awp_wp1'] = result['gva_irrigated'] / result['v_etb_m3']
        result['awp_wp2'] = result['wpb_mean'] * 0.05  # Prix biomasse 0.05 USD/kg
        
        # 6. Calculer irrigation efficiency
        result['irrigation_efficiency'] = result['v_etb_m3'] / result['v_a_m3']
        
        logger.info(f"✓ AWP calculé pour {len(result)} gouvernorats")
        return result
    
    def rank_governorates(
        self,
        gdf: gpd.GeoDataFrame,
        metric: str = 'awp_we',
        ascending: bool = False
    ) -> gpd.GeoDataFrame:
        """
        Classe les gouvernorats selon une métrique.
        
        Args:
            gdf: GeoDataFrame avec métriques
            metric: Nom de la colonne à utiliser pour le classement
            ascending: Si True, ordre croissant
            
        Returns:
            GeoDataFrame trié avec rang
        """
        result = gdf.copy()
        result = result.sort_values(metric, ascending=ascending)
        result['rank'] = range(1, len(result) + 1)
        
        logger.info(f"Gouvernorats classés par {metric}")
        return result
    
    def identify_hotspots(
        self,
        gdf: gpd.GeoDataFrame,
        metric: str,
        threshold_std: float = 1.0
    ) -> gpd.GeoDataFrame:
        """
        Identifie les hotspots (gouvernorats à forte/faible performance).
        
        Args:
            gdf: GeoDataFrame avec métriques
            metric: Nom de la métrique
            threshold_std: Seuil en écarts-types
            
        Returns:
            GeoDataFrame avec classification hotspot
        """
        result = gdf.copy()
        
        mean_val = result[metric].mean()
        std_val = result[metric].std()
        
        z_scores = (result[metric] - mean_val) / std_val
        
        result['z_score'] = z_scores
        result['hotspot'] = 'normal'
        result.loc[z_scores > threshold_std, 'hotspot'] = 'high'
        result.loc[z_scores < -threshold_std, 'hotspot'] = 'low'
        
        logger.info(f"Hotspots identifiés: {metric}")
        logger.info(f"  High: {(result['hotspot']=='high').sum()}")
        logger.info(f"  Normal: {(result['hotspot']=='normal').sum()}")
        logger.info(f"  Low: {(result['hotspot']=='low').sum()}")
        
        return result
