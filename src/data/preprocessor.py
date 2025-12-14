"""
Module de prétraitement des données.
"""

import logging
from typing import Optional, Tuple

import numpy as np
import xarray as xr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataPreprocessor:
    """Classe pour prétraiter les données WaPOR."""
    
    def __init__(self, nodata_value: float = -9999):
        """
        Initialise le préprocesseur.
        
        Args:
            nodata_value: Valeur de données manquantes
        """
        self.nodata_value = nodata_value
        logger.info("DataPreprocessor initialisé")
    
    def remove_outliers(
        self,
        data: xr.DataArray,
        method: str = "iqr",
        threshold: float = 3.0
    ) -> xr.DataArray:
        """
        Supprime les valeurs aberrantes.
        
        Args:
            data: Données à nettoyer
            method: Méthode (iqr, zscore)
            threshold: Seuil pour la détection
            
        Returns:
            Données nettoyées
        """
        logger.info(f"Suppression des outliers avec méthode: {method}")
        
        if method == "iqr":
            q1 = data.quantile(0.25)
            q3 = data.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            return data.where((data >= lower) & (data <= upper))
        
        elif method == "zscore":
            mean = data.mean()
            std = data.std()
            z_scores = np.abs((data - mean) / std)
            return data.where(z_scores < threshold)
        
        return data
    
    def mask_by_land_cover(
        self,
        data: xr.DataArray,
        lcc: xr.DataArray,
        classes: list
    ) -> xr.DataArray:
        """
        Masque les données selon les classes de couverture terrestre.
        
        Args:
            data: Données à masquer
            lcc: Classification de couverture terrestre
            classes: Classes à conserver
            
        Returns:
            Données masquées
        """
        logger.info(f"Masquage par classes de couverture: {classes}")
        mask = lcc.isin(classes)
        return data.where(mask)
    
    def resample_temporal(
        self,
        data: xr.DataArray,
        freq: str = "1Y"
    ) -> xr.DataArray:
        """
        Rééchantillonne temporellement les données.
        
        Args:
            data: Données à rééchantillonner
            freq: Fréquence (1Y=annuel, 1M=mensuel, etc.)
            
        Returns:
            Données rééchantillonnées
        """
        logger.info(f"Rééchantillonnage temporel: {freq}")
        return data.resample(time=freq).sum()
