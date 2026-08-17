import os
import re
from typing import List
from difflib import SequenceMatcher
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Config from env
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SETLISTFM_API_KEY = os.getenv("SETLISTFM_API_KEY")

if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET or not SPOTIPY_REDIRECT_URI:
    raise RuntimeError("Please set SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI")

SCOPE = "playlist-modify-public playlist-modify-private"

app = FastAPI(title="Setlist -> Spotify")

# CORS
origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_spotify_oauth():
    """Helper to create a fresh, un-cached OAuth manager every time."""
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        cache_path=None,  # Disables local .cache file writes
        show_dialog=True,
    )

# ------------------------------------------------------------------
# AUTHENTICATION ROUTES
# ------------------------------------------------------------------

@app.get("/login")
def login():
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        raise HTTPException(status_code=400, detail=f"Spotify auth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code in callback")

    sp_oauth = get_spotify_oauth()
    try:
        token_info = sp_oauth.get_access_token(code, check_cache=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {e}")

    access_token = token_info.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Failed to get access token from Spotify")

    response = RedirectResponse("https://aadilsomani.com/setlisttoplaylist")
    secure_cookie = SPOTIPY_REDIRECT_URI.startswith("https://")
    response.set_cookie(
        key="spotify_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        domain= ".aadilsomani.com",
        path="/",
        max_age=3600
    )
    return response


@app.get("/logout")
def logout(response: Response):
    response = RedirectResponse("/")
    response.delete_cookie("spotify_token")
    return response

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
    """Check if the found Spotify artist matches or is sufficiently similar to the target artist."""
    if not target_artist or not found_artist:
        return True
    
    target = target_artist.lower().strip()
    found = found_artist.lower().strip()
    
    # Substring match (e.g. "The Beatles" vs "Beatles", or featured artists)
    if target in found or found in target:
        return True
        
    # Similarity ratio score
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
        
        # Verify artist match
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
def create_playlist_endpoint(request: Request, payload: dict):
    # 1. Check for logged-in user's token in cookies
    access_token = request.cookies.get("spotify_token")
    if not access_token:
        raise HTTPException(
            status_code=401, 
            detail="User not logged in. Please visit /login first."
        )

    setlist_url = payload.get("setlist_url")
    playlist_name = payload.get("playlist_name")
    public = payload.get("public", False)
    artist_name_hint = payload.get("artist_name")

    if not setlist_url:
        raise HTTPException(status_code=400, detail="Missing setlist_url")

    # 2. Get Songs and Metadata from Setlist
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

    # 3. Create Spotify Client
    try:
        sp = spotipy.Spotify(auth=access_token)
        current_user = sp.me()
        user_id = current_user["id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired or invalid token.")

    # 4. Generate Playlist Title dynamically if not explicitly provided
    if not playlist_name or playlist_name in ["My Real Test Playlist", "Test Concert Playlist"]:
        parts = []
        if artist_name:
            parts.append(artist_name)
        if tour_name:
            parts.append(tour_name)
        if venue_name:
            parts.append(venue_name)

        playlist_name = " - ".join(parts) if parts else "Setlist Playlist"

    print(f"[DEBUG] Final Playlist Name: '{playlist_name}'")

    playlist = sp.user_playlist_create(
        user=user_id, 
        name=playlist_name, 
        public=public,
        description=f"Generated from {setlist_url}"
    )
    playlist_id = playlist["id"]

    # 5. Search, Validate, and Add Tracks
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

    if track_uris:
        for i in range(0, len(track_uris), 100):
            sp.playlist_add_items(playlist_id, track_uris[i:i+100])

    # 6. Return response containing missing songs for UI integration
    return {
        "playlist_id": playlist_id, 
        "playlist_name": playlist_name,
        "spotify_playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "matched_count": len(track_uris),
        "total_count": len(songs),
        "missing_songs": missing_songs
    }

@app.get("/health")
def health():
    return {"status": "ok"}