import os
import re
from typing import List
from difflib import SequenceMatcher
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Config from env
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SETLISTFM_API_KEY = os.getenv("SETLISTFM_API_KEY")

if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    raise RuntimeError("Please set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET")

app = FastAPI(title="Setlist -> Spotify Search Engine")

# CORS
raw_origins = os.getenv("CORS_ORIGINS", "*").split(",")
origins = [origin.strip().strip('"').strip("'").rstrip("/") for origin in raw_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_spotify_client():
    """App-level client. Requires no user login, creates no playlists on your profile!"""
    client_credentials_manager = SpotifyClientCredentials(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET
    )
    return spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# ------------------------------------------------------------------
# SETLIST & PLAYLIST HELPERS
# ------------------------------------------------------------------

def extract_setlist_id_from_url(url: str) -> str:
    print(f"\n[DEBUG] Parsing setlist URL: {url}")
    m = re.search(r"-([0-9a-f]+)\.html", url)
    if m:
        extracted_id = m.group(1)
        print(f"[DEBUG] Extracted setlist ID (regex): {extracted_id}")
        return extracted_id
    
    parts = url.rstrip("/").split("/")
    last = parts[-1]
    extracted_id = last.replace(".html", "")
    print(f"[DEBUG] Extracted setlist ID (fallback path): {extracted_id}")
    return extracted_id


def fetch_setlist_songs_via_api(setlist_id: str) -> tuple[list, dict]:
    if not SETLISTFM_API_KEY:
        raise RuntimeError("SETLISTFM_API_KEY not set")
    
    headers = {"Accept": "application/json", "x-api-key": SETLISTFM_API_KEY}
    r = requests.get(f"https://api.setlist.fm/rest/1.0/setlist/{setlist_id}", headers=headers, timeout=10)
    
    if r.status_code != 200:
        raise RuntimeError(f"setlist.fm API error {r.status_code}: {r.text}")
    
    data = r.json()
    
    metadata = {
        "artist": data.get("artist", {}).get("name"),
        "tour": data.get("tour", {}).get("name"),
        "venue": data.get("venue", {}).get("name"),
    }
    
    print(
        f"[DEBUG] Retrieved metadata -> "
        f"Artist: '{metadata['artist']}', Tour: '{metadata['tour']}', Venue: '{metadata['venue']}'"
    )
    
    songs = []
    sets_data = data.get("sets", {})
    sets = sets_data.get("set", []) if isinstance(sets_data, dict) else []
    
    if not sets and "set" in data:
        sets = data.get("set", [])

    if isinstance(sets, dict):
        sets = [sets]
        
    for s in sets:
        song_items = s.get("song", [])
        if isinstance(song_items, dict):
            song_items = [song_items]
        for song in song_items:
            name = song.get("name")
            if name:
                songs.append(name)
                
    print(f"[DEBUG] Parsed {len(songs)} song(s) from API response.")
    return songs, metadata


def fetch_setlist_songs_fallback_html(url: str) -> tuple[list, dict]:
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch setlist page: {r.status_code}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    songs = []
    for ol in soup.find_all("ol"):
        for li in ol.find_all("li"):
            a = li.find("a")
            if a and a.text:
                songs.append(a.text.strip())
    
    return songs, {}


def is_artist_similar(target_artist: str, found_artist: str, threshold: float = 0.6) -> bool:
    if not target_artist or not found_artist:
        return True
    
    target = target_artist.lower().strip()
    found = found_artist.lower().strip()
    
    if target in found or found in target:
        return True
        
    ratio = SequenceMatcher(None, target, found).ratio()
    return ratio >= threshold


def search_track_on_spotify(sp: spotipy.Spotify, song_name: str, artist_name: str = None) -> str:
    query = song_name
    if artist_name:
        query = f"{song_name} {artist_name}"
        
    print(f"[DEBUG] Searching Spotify for: '{query}'")
    try:
        res = sp.search(q=query, type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        
        if not items:
            print(f"[DEBUG] ❌ No match found on Spotify for: '{song_name}'")
            return None
            
        track = items[0]
        track_uri = track["uri"]
        found_name = track["name"]
        found_artists = [a["name"] for a in track.get("artists", [])]
        
        if artist_name:
            match_found = any(is_artist_similar(artist_name, fa) for fa in found_artists)
            if not match_found:
                print(
                    f"[DEBUG] ⚠️ Artist mismatch for '{song_name}'. "
                    f"Expected: '{artist_name}', Found: {found_artists}. Skipping track."
                )
                return None

        print(f"[DEBUG] ✅ Found: '{found_name}' by {', '.join(found_artists)}")
        return track_uri
        
    except Exception as e:
        print(f"[DEBUG ERROR] Search failed for '{song_name}': {e}")
        return None

# ------------------------------------------------------------------
# MAIN ENDPOINT
# ------------------------------------------------------------------

@app.post("/create_playlist")
def create_playlist_endpoint(payload: dict):
    setlist_url = payload.get("setlist_url")
    playlist_name_hint = payload.get("playlist_name")
    artist_name_hint = payload.get("artist_name")

    if not setlist_url:
        raise HTTPException(status_code=400, detail="Missing setlist_url")

    # 1. Get Songs and Metadata from Setlist
    songs = []
    metadata = {}
    
    try:
        setlist_id = extract_setlist_id_from_url(setlist_url)
        if SETLISTFM_API_KEY:
            songs, metadata = fetch_setlist_songs_via_api(setlist_id)
        else:
            songs, metadata = fetch_setlist_songs_fallback_html(setlist_url)
    except Exception as e:
        print(f"[DEBUG ERROR] setlist.fm API call failed: {e}")
        try:
            songs, metadata = fetch_setlist_songs_fallback_html(setlist_url)
        except Exception as fallback_err:
            raise HTTPException(status_code=500, detail=f"Failed to obtain songs: {fallback_err}")

    if not songs:
        raise HTTPException(status_code=404, detail="No songs found in setlist")

    artist_name = metadata.get("artist") or artist_name_hint or "Unknown Artist"
    tour_name = metadata.get("tour")
    venue_name = metadata.get("venue")

    # 2. Generate Dynamic Playlist Title
    if not playlist_name_hint:
        parts = [p for p in [artist_name, tour_name, venue_name] if p]
        playlist_name = " - ".join(parts) if parts else "Setlist Playlist"
    else:
        playlist_name = playlist_name_hint

    print(f"[DEBUG] Final Playlist Title: '{playlist_name}'")

    # 3. Search and Validate Tracks via App-Level Spotify Client (No User Account!)
    sp = get_spotify_client()
    
    track_uris = []
    missing_songs = []
    
    print("\n[DEBUG] --- STARTING SPOTIFY SEARCH ---")
    
    for song in songs:
        uri = search_track_on_spotify(sp, song, artist_name)
        if uri:
            track_uris.append(uri)
        else:
            missing_songs.append(song)

    print(f"\n[DEBUG] Successfully matched {len(track_uris)} out of {len(songs)} tracks.")
    if missing_songs:
        print(f"[DEBUG] Missing or skipped songs ({len(missing_songs)}): {missing_songs}")

    # 4. Return data to frontend for user-side playlist creation
    return {
        "playlist_name": playlist_name,
        "matched_count": len(track_uris),
        "total_count": len(songs),
        "track_uris": track_uris,
        "missing_songs": missing_songs
    }

@app.get("/health")
def health():
    return {"status": "ok"}