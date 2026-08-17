import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

# Read configuration from environment variables (do NOT commit secrets)
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
USERNAME = os.getenv("SPOTIFY_USER_ID", "")

# Request scopes for creating and editing playlists
scope = "playlist-modify-public playlist-modify-private"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID or None,
    client_secret=CLIENT_SECRET or None,
    redirect_uri=REDIRECT_URI,
    scope=scope
))

def scrapeSetlistFM(url="https://www.setlist.fm/setlist/jeremy-zucker/2025/the-van-buren-phoenix-az-53435b21.html"):
    """
    Scrape song titles and artist name from a setlist.fm page using Selenium
    
    Args:
        url: The setlist.fm URL to scrape
        
    Returns:
        tuple: (artist_name, list_of_songs) or (None, []) if error
    """
    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in background
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    try:
        # Set up the driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print(f"Loading setlist from: {url}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(3)
        
        # Scrape artist name
        artist_element = driver.find_element(By.XPATH, "/html/body/div[2]/div[3]/div[3]/div[1]/div[1]/div[1]/div[2]/div/h1/strong/span/a/span")
        artist_name = artist_element.text.strip()
        print(f"Found artist: {artist_name}")
        
        # Find all song list items
        # Based on the xpath pattern provided: /html/body/div[2]/div[3]/div[3]/div[1]/div[1]/div[3]/div[1]/div[2]/ol/li[1]/div[1]/a
        # We'll look for all li elements in the setlist and then find the a tags within them
        song_elements = driver.find_elements(By.XPATH, "//ol/li//div//a[@title]")
        
        songs = []
        for element in song_elements:
            song_title = element.text.strip()
            if song_title:  # Only add non-empty titles
                songs.append(song_title)
                print(f"Found song: {song_title}")
        
        driver.quit()
        
        print(f"\nTotal songs found: {len(songs)}")
        return artist_name, songs
        
    except Exception as e:
        print(f"Error scraping setlist: {e}")
        if 'driver' in locals():
            driver.quit()
        return None, []


# ---------- Create a playlist ----------
def create_playlist(name, description="", public=False):
    playlist = sp.user_playlist_create(
        user=USERNAME,
        name=name,
        public=public,
        description=description
    )
    print("Created playlist:", playlist["name"], "ID:", playlist["id"])
    return playlist["id"]

# ---------- Add a song by name and artist ----------
def add_song_to_playlist(playlist_id, song_name, artist_name):
    query = f"track:{song_name} artist:{artist_name}"
    results = sp.search(q=query, type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
        print(f"❗ No match found for {song_name} by {artist_name}")
        return
    track_id = items[0]["id"]
    sp.playlist_add_items(playlist_id, [track_id])
    print(f"✅ Added {song_name} by {artist_name}")


def create_playlist_from_songs(songs, artist_name, playlist_name, setlist_url=None):
    """
    Create a Spotify playlist from a list of songs
    
    Args:
        songs: List of song titles
        artist_name: Name of the artist for searching songs
        playlist_name: Name for the playlist
        setlist_url: Optional URL for playlist description
        
    Returns:
        str: Playlist ID if successful, None otherwise
    """
    if not songs:
        print("No songs provided for playlist")
        return None
    
    # Create playlist description
    description = f"Setlist from {setlist_url}" if setlist_url else f"Playlist for {artist_name}"
    
    # Create the playlist
    playlist_id = create_playlist(
        name=playlist_name,
        description=description,
        public=False
    )
    
    # Add songs to playlist
    for song in songs:
        add_song_to_playlist(playlist_id, song, artist_name)
    
    return playlist_id


def create_playlist_from_setlist(setlist_url, playlist_name=None):
    """
    Create a Spotify playlist from a setlist.fm page
    
    Args:
        setlist_url: URL of the setlist.fm page
        playlist_name: Optional custom playlist name
        
    Returns:
        str: Playlist ID if successful, None otherwise
    """
    # Scrape the setlist
    artist_name, songs = scrapeSetlistFM(setlist_url)
    
    if not songs or not artist_name:
        print("No songs or artist found in setlist")
        return None
    
    # Create playlist name if not provided
    if not playlist_name:
        playlist_name = f"{artist_name} - Setlist"
    
    return create_playlist_from_songs(songs, artist_name, playlist_name, setlist_url)


if __name__ == "__main__":
    # Test scraping
    print("Testing setlist scraping...")
    test_url = "https://www.setlist.fm/setlist/twenty-one-pilots/2025/tql-stadium-cincinnati-oh-73443e59.html"
    artist_name, songs = scrapeSetlistFM(test_url)
    
    if songs and artist_name:
        print(f"\nArtist: {artist_name}")
        print(f"Songs found: {songs}")
        
        # Create a playlist from the already scraped songs
        print("\nCreating Spotify playlist...")
        playlist_id = create_playlist_from_songs(songs, artist_name, f"{artist_name} - TQL Stadium 2025", test_url)
        
        if playlist_id:
            print(f"\n🎉 Successfully created playlist with ID: {playlist_id}")
            print("Check your Spotify account for the new playlist!")
        else:
            print("❌ Failed to create playlist")
    else:
        print("No songs or artist found")