"""
Module pour charger les données téléchargées.
"""

import logging
from pathlib import Path
from typing import Optional, Union

import xarray as xr
import rasterio
import geopandas as gpd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataLoader:
    """Classe pour charger différents types de données."""
    
    def __init__(self, data_root: str = "../data"):
        """
        Initialise le chargeur de données.
        
        Args:
            data_root: Répertoire racine des données
        """
        self.data_root = Path(data_root)
        logger.info(f"DataLoader initialisé avec racine: {data_root}")
    
    def load_raster(self, filepath: str) -> xr.DataArray:
        """
        Charge un fichier raster.
        
        Args:
            filepath: Chemin vers le fichier raster
            
        Returns:
            DataArray xarray
        """
        logger.info(f"Chargement du raster: {filepath}")
        return xr.open_dataarray(filepath)
    
    def load_vector(self, filepath: str) -> gpd.GeoDataFrame:
        """
        Charge un fichier vectoriel.
        
        Args:
            filepath: Chemin vers le fichier vectoriel
            
        Returns:
            GeoDataFrame
        """
        logger.info(f"Chargement du vecteur: {filepath}")
        return gpd.read_file(filepath)
    
    def load_et_data(self, year: int) -> xr.Dataset:
        """Charge les données ET pour une année donnée."""
        # TODO: Implémenter
        pass
    
    def load_lcc_data(self, year: Optional[int] = None) -> xr.DataArray:
        """Charge les données de classification de couverture terrestre."""
        # TODO: Implémenter
        pass
