import pandas as pd
import os
from typing import List, Dict, Any

class DrugCentralService:
    def __init__(self, drugcentral_dir: str):
        self.drugcentral_dir = drugcentral_dir
        self.target_df = None
        self._load_data()

    def _load_data(self):
        if not self.drugcentral_dir:
            print("DrugCentral directory not configured.")
            self.target_df = pd.DataFrame()
            return
            
        interaction_path_gz = os.path.join(self.drugcentral_dir, "drug.target.interaction.tsv.gz")
        interaction_path = os.path.join(self.drugcentral_dir, "drug.target.interaction.tsv")
        
        path_to_load = interaction_path_gz if os.path.exists(interaction_path_gz) else interaction_path
        
        try:
            print(f"Loading DrugCentral from {path_to_load}...")
            self.target_df = pd.read_csv(path_to_load, sep='\t', low_memory=False)
            if 'DRUG_NAME' in self.target_df.columns:
                self.target_df['DRUG_NAME_LOWER'] = self.target_df['DRUG_NAME'].astype(str).str.lower()
            print(f"Loaded {len(self.target_df)} drug-target interactions.")
        except Exception as e:
            print(f"Failed to load DrugCentral interactions: {e}")
            self.target_df = pd.DataFrame()

    def get_drug_targets(self, drug_name: str) -> List[Dict[str, Any]]:
        """
        Retrieves known targets for a given drug name.
        """
        if self.target_df is None or self.target_df.empty:
            return []
            
        drug_name = drug_name.lower()
        matches = self.target_df[self.target_df['DRUG_NAME_LOWER'] == drug_name]
        
        targets = []
        for _, row in matches.iterrows():
            # Handle potential NaNs
            target_name = row.get("TARGET_NAME")
            target_class = row.get("TARGET_CLASS")
            gene = row.get("GENE")
            action_type = row.get("ACTION_TYPE")
            
            targets.append({
                "target_name": target_name if pd.notna(target_name) else None,
                "target_class": target_class if pd.notna(target_class) else None,
                "gene": gene if pd.notna(gene) else None,
                "action_type": action_type if pd.notna(action_type) else None
            })
            
        return targets
