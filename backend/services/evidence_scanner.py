import requests
import json
from typing import List, Dict, Any
from backend.schemas.patient import PatientContext
from backend.config import settings

class EvidenceScannerAgent:
    def __init__(self):
        self.api_key = settings.SERPER_API_KEY
        self.url = "https://google.serper.dev/search"

    def search(self, context: PatientContext) -> List[Dict[str, Any]]:
        """
        Queries the Serper API for clinical guidelines and evidence.
        """
        results = []
        
        if not self.api_key or (not context.symptoms and not context.known_conditions):
            return results
            
        # Formulate query
        query_terms = [s.normalized_name or s.text for s in context.symptoms] + \
                      [c.normalized_name or c.text for c in context.known_conditions]
        
        query_string = f"clinical guidelines {' '.join(query_terms)} treatment diagnosis"
        print(f"EvidenceScannerAgent: Executing Live Web Search for: '{query_string}'")
        
        payload = json.dumps({
            "q": query_string,
            "num": 3 # Fetch top 3 results
        })
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(self.url, headers=headers, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Parse organic search results
            organic_results = data.get("organic", [])
            for res in organic_results:
                results.append({
                    "title": res.get("title", ""),
                    "snippet": res.get("snippet", ""),
                    "source": "Serper Web Search",
                    "url": res.get("link", "")
                })
        except requests.exceptions.RequestException as e:
            print(f"EvidenceScannerAgent API Error: {e}")
        
        return results
