import requests
import time
import os
import re
import json
import threading
import concurrent.futures

BASE_URL = "http://127.0.0.1:3001/v2"
EXPORT_DIR = "vlr_json_database"
PROGRESS_FILE = os.path.join(EXPORT_DIR, "progress.json")
MAX_PAGES = 1000000  # Limite de sécurité pour boucler jusqu'à la fin
DELAY = 1          # Pause entre chaque requête

os.makedirs(EXPORT_DIR, exist_ok=True)

# Verrou pour sécuriser l'écriture simultanée dans les fichiers JSONL par 4 threads
file_lock = threading.Lock()

class ScrapingState:
    """Gestionnaire thread-safe pour distribuer les pages aux différents workers."""
    def __init__(self):
        self.lock = threading.Lock()
        self.events_done = False
        self.matches_done = False
        
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.events_page = data.get("events_page", 1)
                self.matches_page = data.get("matches_page", 1)
        else:
            self.events_page = 1
            self.matches_page = 1

    def next_events_page(self):
        """Donne la prochaine page d'événements disponible à un worker."""
        with self.lock:
            if self.events_done or self.events_page > MAX_PAGES:
                return None
            p = self.events_page
            self.events_page += 1
            self._save()
            return p

    def next_matches_page(self):
        """Donne la prochaine page de matchs disponible à un worker."""
        with self.lock:
            if self.matches_done or self.matches_page > MAX_PAGES:
                return None
            p = self.matches_page
            self.matches_page += 1
            self._save()
            return p

    def mark_events_done(self):
        with self.lock:
            self.events_done = True

    def mark_matches_done(self):
        with self.lock:
            self.matches_done = True

    def _save(self):
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "events_page": self.events_page,
                "matches_page": self.matches_page
            }, f, indent=4)

# Instance globale de l'état d'avancement
state = ScrapingState()

def fetch_api(endpoint):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return data.get("data")
    except Exception as e:
        print(f"[!] Erreur sur {endpoint} : {e}")
    return None

def save_to_jsonl(table_name, data):
    if not data:
        return
    filepath = os.path.join(EXPORT_DIR, f"{table_name}.jsonl")
    
    # Le verrou garantit que les lignes JSON ne se mélangent pas dans le fichier
    with file_lock:
        with open(filepath, mode="a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")

def extract_id_from_url(url_path):
    match = re.search(r'/(\d+)/', url_path)
    return match.group(1) if match else None

def process_events(worker_id):
    print(f"\n[Events-Worker-{worker_id}] Démarrage...")
    while True:
        page = state.next_events_page()
        if page is None:
            break
            
        print(f"[Events-Worker-{worker_id}] Extraction événements (Page {page})...")
        events_data = fetch_api(f"/events?q=completed&page={page}")
        
        if not events_data or not events_data.get("segments"):
            print(f"[Events-Worker-{worker_id}] Fin de l'historique atteinte.")
            state.mark_events_done()
            break
            
        for event in events_data["segments"]:
            save_to_jsonl("events_global", event)
            event_id = extract_id_from_url(event.get("url_path", ""))
            if event_id:
                time.sleep(DELAY)
                event_details = fetch_api(f"/event/{event_id}")
                if event_details and "segments" in event_details:
                    raw_detail = event_details["segments"]
                    raw_detail["event_id_reference"] = event_id
                    save_to_jsonl("events_details", raw_detail)
        time.sleep(DELAY)

def process_matches(worker_id):
    print(f"\n[Matches-Worker-{worker_id}] Démarrage...")
    while True:
        page = state.next_matches_page()
        if page is None:
            break
            
        print(f"[Matches-Worker-{worker_id}] Extraction matchs (Page {page})...")
        matches_data = fetch_api(f"/match?q=results&from_page={page}&to_page={page}")
        
        if not matches_data or not matches_data.get("segments"):
            print(f"[Matches-Worker-{worker_id}] Fin de l'historique atteinte.")
            state.mark_matches_done()
            break
            
        for match in matches_data["segments"]:
            save_to_jsonl("matches_global", match)
            match_id = extract_id_from_url(match.get("match_page", ""))
            if match_id:
                time.sleep(DELAY)
                match_details = fetch_api(f"/match/details?match_id={match_id}")
                if match_details:
                    save_to_jsonl("matches_details", match_details)
        time.sleep(DELAY)

def main():
    print("Démarrage du pipeline ETL (JSONL) avec 4 Threads (Cœurs)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Lancement de 2 coeurs pour les événements
        future_e1 = executor.submit(process_events, 1)
        future_e2 = executor.submit(process_events, 2)
        
        # Lancement de 2 coeurs pour les matchs
        future_m1 = executor.submit(process_matches, 1)
        future_m2 = executor.submit(process_matches, 2)
        
        # Attente que les 4 threads terminent leur travail
        concurrent.futures.wait([future_e1, future_e2, future_m1, future_m2])
    
    print(f"\nExtraction terminée ! Les données sont organisées dans le dossier : {EXPORT_DIR}")

if __name__ == "__main__":
    main()