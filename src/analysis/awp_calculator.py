"""
Module pour calculer la productivité de l'eau agricole (AWP) selon SDG 6.4.1.

Trois approches:
1. A_we:  Approche classique AQUASTAT (référence)
2. A_wp1: Satellites (ETb) + Économie (GVA)
3. A_wp2: 100% satellites (WPb converti en valeur économique)

Formules:
- A_we  = (GVA_a × (1-c_r)) / V_a
- A_wp1 = (GVA_a × (1-c_r)) / V_ETb
- A_wp2 = WPb_mean × biomass_price

Où:
- GVA_a: Valeur ajoutée brute agricole (USD)
- V_a: Volume d'eau retirés pour l'agriculture (m³) [AQUASTAT]
- V_ETb: Volume d'eau calculé par satellites (m³)
- c_r: Proportion rainfed vs irrigué
- WPb_mean: Productivité biomasse moyenne (kg/m³)
- biomass_price: Prix de la biomasse (USD/kg)
"""

import logging
from typing import Tuple, Dict, Optional
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AWPCalculator:
    """
    Classe pour calculer les trois approches de productivité de l'eau agricole (AWP).
    
    Références:
    - SDG 6.4.1 Indicator
    - FAO AQUASTAT
    - Article: "Estimating agricultural water productivity using remote sensing" (2023)
    """
    
    def __init__(self, biomass_price: float = 0.05):
        """
        Initialise le calculateur AWP.
        
        Args:
            biomass_price: Prix de la biomasse (USD/kg), défaut: 0.05 USD/kg
        """
        self.biomass_price = biomass_price
        logger.info(f"AWPCalculator initialisé (biomass_price={biomass_price} USD/kg)")
    
    def calculate_a_we(
        self,
        gva_a: float,
        v_a: float,
        c_r: float
    ) -> float:
        """
        Calcule A_we (approche classique AQUASTAT).
        
        Formule: A_we = (GVA_a × (1-c_r)) / V_a
        
        Args:
            gva_a: Valeur ajoutée brute agricole (USD)
            v_a: Volume d'eau retirés pour agriculture (m³)
            c_r: Proportion rainfed (0-1)
            
        Returns:
            A_we (USD/m³)
        """
        logger.info("Calcul de A_we (AQUASTAT)")
        
        if v_a <= 0:
            logger.warning("V_a <= 0, impossible de calculer A_we")
            return np.nan
        
        a_we = (gva_a * (1 - c_r)) / v_a
        
        logger.info(f"  A_we = {a_we:.4f} USD/m³")
        return a_we
    
    def calculate_a_wp1(
        self,
        gva_a: float,
        v_etb: float,
        c_r: float
    ) -> float:
        """
        Calcule A_wp1 (satellites ETb + économie AQUASTAT).
        
        Formule: A_wp1 = (GVA_a × (1-c_r)) / V_ETb
        
        Args:
            gva_a: Valeur ajoutée brute agricole (USD)
            v_etb: Volume ETb calculé par satellites (m³)
            c_r: Proportion rainfed (0-1)
            
        Returns:
            A_wp1 (USD/m³)
        """
        logger.info("Calcul de A_wp1 (Satellites + GVA)")
        
        if v_etb <= 0:
            logger.warning("V_ETb <= 0, impossible de calculer A_wp1")
            return np.nan
        
        a_wp1 = (gva_a * (1 - c_r)) / v_etb
        
        logger.info(f"  A_wp1 = {a_wp1:.4f} USD/m³")
        return a_wp1
    
    def calculate_a_wp2(
        self,
        wpb_mean: float,
        biomass_price: Optional[float] = None
    ) -> float:
        """
        Calcule A_wp2 (100% satellites).
        
        Formule: A_wp2 = WPb_mean × biomass_price
        
        Args:
            wpb_mean: Productivité biomasse moyenne (kg/m³)
            biomass_price: Prix biomasse (USD/kg), utilise self.biomass_price si None
            
        Returns:
            A_wp2 (USD/m³)
        """
        logger.info("Calcul de A_wp2 (100% satellites)")
        
        price = biomass_price if biomass_price is not None else self.biomass_price
        
        a_wp2 = wpb_mean * price
        
        logger.info(f"  A_wp2 = {a_wp2:.4f} USD/m³")
        return a_wp2
    
    def calculate_v_etb(
        self,
        etb_raster: np.ndarray,
        cropland_mask: np.ndarray,
        pixel_area_m2: float
    ) -> float:
        """
        Calcule le volume total d'eau ETb (V_ETb).
        
        Formule: V_ETb = sum(ETb × pixel_area × cropland_fraction) / 1000
        
        Args:
            etb_raster: Raster ETb (mm/an)
            cropland_mask: Masque cropland (fraction 0-1)
            pixel_area_m2: Surface d'un pixel (m²)
            
        Returns:
            V_ETb (m³)
        """
        logger.info("Calcul de V_ETb (volume total)")
        
        # Créer un masque pour les valeurs valides (ETb >= 0, cropland > 0)
        valid_mask = (etb_raster >= 0) & (cropland_mask > 0) & (~np.isnan(etb_raster)) & (~np.isnan(cropland_mask))
        
        # ETb en mm → m: diviser par 1000
        etb_m = etb_raster / 1000.0
        
        # Volume total (m³) - seulement sur pixels valides
        v_etb = np.sum(etb_m[valid_mask] * pixel_area_m2 * cropland_mask[valid_mask])
        
        logger.info(f"  V_ETb = {v_etb:,.0f} m³")
        logger.info(f"  Pixels valides: {np.sum(valid_mask):,}")
        return v_etb
    
    def calculate_all_awp(
        self,
        year: int,
        gva_a: float,
        v_a: float,
        c_r: float,
        etb_raster: np.ndarray,
        cropland_mask: np.ndarray,
        pixel_area_m2: float,
        wpb_mean: float
    ) -> Dict:
        """
        Calcule les trois approches AWP pour une année.
        
        Args:
            year: Année
            gva_a: Valeur ajoutée brute agricole (USD)
            v_a: Volume AQUASTAT (m³)
            c_r: Proportion rainfed
            etb_raster: Raster ETb (mm/an)
            cropland_mask: Masque cropland
            pixel_area_m2: Surface pixel (m²)
            wpb_mean: WPb moyen (kg/m³)
            
        Returns:
            Dictionnaire avec A_we, A_wp1, A_wp2, V_ETb
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Calcul AWP - Année {year}")
        logger.info(f"{'='*60}")
        
        # Calculer V_ETb
        v_etb = self.calculate_v_etb(etb_raster, cropland_mask, pixel_area_m2)
        
        # Calculer les trois approches
        a_we = self.calculate_a_we(gva_a, v_a, c_r)
        a_wp1 = self.calculate_a_wp1(gva_a, v_etb, c_r)
        a_wp2 = self.calculate_a_wp2(wpb_mean)
        
        results = {
            'year': year,
            'A_we': a_we,
            'A_wp1': a_wp1,
            'A_wp2': a_wp2,
            'V_a': v_a,
            'V_ETb': v_etb,
            'GVA_a': gva_a,
            'c_r': c_r,
            'WPb_mean': wpb_mean
        }
        
        logger.info(f"\nRésultats {year}:")
        logger.info(f"  A_we  = {a_we:.4f} USD/m³")
        logger.info(f"  A_wp1 = {a_wp1:.4f} USD/m³")
        logger.info(f"  A_wp2 = {a_wp2:.4f} USD/m³")
        logger.info(f"  V_a   = {v_a:,.0f} m³")
        logger.info(f"  V_ETb = {v_etb:,.0f} m³")
        
        return results
    
    def compare_awp_methods(self, results_list: list) -> pd.DataFrame:
        """
        Compare les trois méthodes AWP sur plusieurs années.
        
        Args:
            results_list: Liste de dictionnaires de résultats
            
        Returns:
            DataFrame avec comparaison
        """
        df = pd.DataFrame(results_list)
        
        # Calculer les différences relatives
        df['diff_wp1_we'] = ((df['A_wp1'] - df['A_we']) / df['A_we']) * 100
        df['diff_wp2_we'] = ((df['A_wp2'] - df['A_we']) / df['A_we']) * 100
        
        logger.info("\n" + "="*60)
        logger.info("Comparaison des méthodes AWP")
        logger.info("="*60)
        logger.info(f"\nMoyenne période {df['year'].min()}-{df['year'].max()}:")
        logger.info(f"  A_we  = {df['A_we'].mean():.4f} USD/m³")
        logger.info(f"  A_wp1 = {df['A_wp1'].mean():.4f} USD/m³ ({df['diff_wp1_we'].mean():+.1f}%)")
        logger.info(f"  A_wp2 = {df['A_wp2'].mean():.4f} USD/m³ ({df['diff_wp2_we'].mean():+.1f}%)")
        
        return df
