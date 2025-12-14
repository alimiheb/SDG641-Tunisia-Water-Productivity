"""
Module pour calculer l'évapotranspiration bleue (ETb) selon la méthodologie SDG 6.4.1.

Formule principale: ETb = max(AETI - P_effective, 0)

Où:
- AETI: Actual Evapotranspiration and Interception (mm/an)
- P_effective: Précipitations effectives (mm/an)
- ETb: Blue Evapotranspiration - eau d'irrigation utilisée (mm/an)
"""

import logging
from typing import Optional, Tuple, Dict
import os

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ETbCalculator:
    """
    Classe pour calculer ETb selon la méthodologie SDG 6.4.1.
    
    Références:
    - FAO WaPOR: https://wapor.apps.fao.org/
    - Brouwer & Heibloem (1986): Effective precipitation formula
    """
    
    def __init__(self, peff_factor: float = 0.7):
        """
        Initialise le calculateur ETb.
        
        Args:
            peff_factor: Facteur de précipitations effectives (défaut: 0.7)
                        P_effective ≈ 0.7 * P_annual (approximation)
        """
        self.peff_factor = peff_factor
        logger.info(f"ETbCalculator initialisé (P_eff factor={peff_factor})")
    
    def calculate_effective_precipitation(self, pcp_monthly: np.ndarray) -> np.ndarray:
        """
        Calcule les précipitations effectives selon Brouwer & Heibloem (1986).
        
        Formules:
        - Si P > 75 mm/mois: P_e = max(0.8 * P - 25, 0)
        - Sinon:             P_e = max(0.6 * P - 10, 0)
        
        Args:
            pcp_monthly: Précipitations mensuelles (mm/mois)
            
        Returns:
            Précipitations effectives (mm/mois)
        """
        pcp_monthly = np.asarray(pcp_monthly, dtype=np.float32)
        pcp_effective = np.zeros_like(pcp_monthly)
        
        # Cas 1: P > 75 mm
        mask_high = pcp_monthly > 75
        pcp_effective[mask_high] = np.maximum(0.8 * pcp_monthly[mask_high] - 25, 0)
        
        # Cas 2: P <= 75 mm
        mask_low = ~mask_high
        pcp_effective[mask_low] = np.maximum(0.6 * pcp_monthly[mask_low] - 10, 0)
        
        return pcp_effective
    
    def align_raster(
        self,
        source_data: np.ndarray,
        source_transform,
        source_crs,
        reference_shape: tuple,
        reference_transform,
        reference_crs,
        resampling_method=Resampling.bilinear
    ) -> np.ndarray:
        """
        Aligner un raster à une grille de référence.
        
        Args:
            source_data: Données source
            source_transform: Transformation affine source
            source_crs: CRS source
            reference_shape: Dimensions (height, width) de référence
            reference_transform: Transformation de référence
            reference_crs: CRS de référence
            resampling_method: Méthode de rééchantillonnage
            
        Returns:
            Données alignées
        """
        aligned_data = np.zeros(reference_shape, dtype=np.float32)
        
        reproject(
            source=source_data,
            destination=aligned_data,
            src_transform=source_transform,
            src_crs=source_crs,
            dst_transform=reference_transform,
            dst_crs=reference_crs,
            resampling=resampling_method
        )
        
        return aligned_data
    
    def calculate_etb(
        self,
        aeti_file: str,
        pcp_file: str,
        cropland_mask: Optional[np.ndarray] = None,
        use_annual_approximation: bool = True
    ) -> Tuple[np.ndarray, np.ndarray, Dict]:
        """
        Calcule ETb pour une année.
        
        Formule: ETb = max(AETI - P_effective, 0)
        
        Args:
            aeti_file: Chemin vers le fichier AETI (GeoTIFF)
            pcp_file: Chemin vers le fichier PCP (GeoTIFF)
            cropland_mask: Masque optionnel des terres cultivées
            use_annual_approximation: Utiliser approximation annuelle (P_eff ≈ 0.7 * P)
            
        Returns:
            (etb_annual, etb_cropland, statistics)
        """
        logger.info(f"Calcul de ETb")
        logger.info(f"  AETI: {os.path.basename(aeti_file)}")
        logger.info(f"  PCP:  {os.path.basename(pcp_file)}")
        
        # Charger AETI (référence spatiale)
        with rasterio.open(aeti_file) as src:
            aeti_annual = src.read(1).astype(np.float32)
            aeti_annual[aeti_annual < 0] = np.nan
            aeti_profile = src.profile
            aeti_transform = src.transform
            aeti_crs = src.crs
            reference_shape = aeti_annual.shape
        
        # Charger PCP
        with rasterio.open(pcp_file) as src:
            pcp_raw = src.read(1).astype(np.float32)
            pcp_raw[pcp_raw < 0] = np.nan
            pcp_transform = src.transform
            pcp_crs = src.crs
        
        # Aligner PCP si nécessaire
        if pcp_raw.shape != reference_shape:
            logger.info(f"  Rééchantillonnage PCP: {pcp_raw.shape} → {reference_shape}")
            pcp_annual = self.align_raster(
                pcp_raw, pcp_transform, pcp_crs,
                reference_shape, aeti_transform, aeti_crs,
                resampling_method=Resampling.bilinear
            )
        else:
            pcp_annual = pcp_raw
        
        # Calculer P_effective
        if use_annual_approximation:
            pcp_effective = self.peff_factor * pcp_annual
            logger.info(f"  P_effective ≈ {self.peff_factor} * P_annual")
        else:
            # Utiliser la formule de Brouwer & Heibloem (nécessite données mensuelles)
            pcp_effective = self.calculate_effective_precipitation(pcp_annual)
        
        # Calculer ETb
        etb_annual = np.maximum(aeti_annual - pcp_effective, 0)
        
        # Appliquer masque cropland
        etb_cropland = etb_annual.copy()
        if cropland_mask is not None:
            etb_cropland = etb_annual * cropland_mask
            etb_cropland[cropland_mask == 0] = np.nan
        
        # Statistiques
        stats = {
            'etb_min': float(np.nanmin(etb_cropland)),
            'etb_max': float(np.nanmax(etb_cropland)),
            'etb_mean': float(np.nanmean(etb_cropland)),
            'etb_median': float(np.nanmedian(etb_cropland)),
            'etb_std': float(np.nanstd(etb_cropland)),
            'aeti_mean': float(np.nanmean(aeti_annual)),
            'pcp_mean': float(np.nanmean(pcp_annual))
        }
        
        logger.info(f"  ETb moyen: {stats['etb_mean']:.1f} mm/an")
        
        return etb_annual, etb_cropland, stats
    
    def calculate_wpb(
        self,
        tbp_file: str,
        etb_annual: np.ndarray,
        etb_profile: dict,
        cropland_mask: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray, Dict]:
        """
        Calcule WPb (Water Productivity of Biomass).
        
        Formule: WPb = TBP / ETb (kg/m³)
        
        Args:
            tbp_file: Chemin vers fichier TBP (GeoTIFF)
            etb_annual: ETb calculé (mm/an)
            etb_profile: Profil rasterio de ETb
            cropland_mask: Masque optionnel des terres cultivées
            
        Returns:
            (wpb_annual, wpb_cropland, statistics)
        """
        logger.info(f"Calcul de WPb")
        logger.info(f"  TBP: {os.path.basename(tbp_file)}")
        
        if not os.path.exists(tbp_file):
            logger.warning(f"  Fichier TBP introuvable: {tbp_file}")
            return None, None, None
        
        # Charger TBP
        with rasterio.open(tbp_file) as src:
            tbp_raw = src.read(1).astype(np.float32)
            tbp_raw[tbp_raw < 0] = np.nan
            tbp_transform = src.transform
            tbp_crs = src.crs
        
        # Aligner TBP si nécessaire
        reference_shape = etb_annual.shape
        if tbp_raw.shape != reference_shape:
            logger.info(f"  Rééchantillonnage TBP: {tbp_raw.shape} → {reference_shape}")
            tbp_annual = self.align_raster(
                tbp_raw, tbp_transform, tbp_crs,
                reference_shape, etb_profile['transform'], etb_profile['crs'],
                resampling_method=Resampling.bilinear
            )
        else:
            tbp_annual = tbp_raw
        
        # Convertir ETb de mm/an en m³/ha
        # 1 mm/an = 10 m³/ha
        etb_m3_ha = etb_annual * 10
        
        # Calculer WPb = TBP / ETb (kg/m³)
        wpb_annual = np.where(etb_m3_ha > 0, tbp_annual / etb_m3_ha, np.nan)
        
        # Appliquer masque cropland
        wpb_cropland = wpb_annual.copy()
        if cropland_mask is not None:
            wpb_cropland = wpb_annual * cropland_mask
            wpb_cropland[cropland_mask == 0] = np.nan
        
        # Statistiques
        stats = {
            'wpb_min': float(np.nanmin(wpb_cropland)),
            'wpb_max': float(np.nanmax(wpb_cropland)),
            'wpb_mean': float(np.nanmean(wpb_cropland)),
            'wpb_median': float(np.nanmedian(wpb_cropland)),
            'wpb_std': float(np.nanstd(wpb_cropland)),
            'tbp_mean': float(np.nanmean(tbp_annual))
        }
        
        logger.info(f"  WPb moyen: {stats['wpb_mean']:.2f} kg/m³")
        
        return wpb_annual, wpb_cropland, stats
