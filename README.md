# Setlist to Spotify Playlist Generator

An automation tool that scrapes concert setlists from **Setlist.fm** using Selenium and automatically recreates them as personal playlists on **Spotify** via the Spotipy API. 

## Features
* **Automated Scraping:** Uses headless Chrome via Selenium to extract artist names and song tracks directly from any Setlist.fm URL.
* **Smart Search:** Leverages the Spotify Web API to target exact matches based on track titles and artist filters.
* **Bulk Creation:** Dynamically instantiates a new Spotify playlist, formats meta-descriptions with source attribution, and appends the matched tracks sequentially.

## Prerequisites
1. **Python 3.x**
2. **Google Chrome** installed on your machine.
3. **Spotify Developer Account** to retrieve API credentials.

## Setup & Installation

### 1. Install Dependencies
```bash
pip install spotipy selenium webdriver-manager
```

### 2. Spotify API Configuration
1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/) and log in.
2. Click **Create App**, give it a name, and add `http://127.0.0.1:8888/callback` as a **Redirect URI**.
3. Open the script and input your credentials into the configuration block:
   ```python
   CLIENT_ID = "your_client_id_here"
   CLIENT_SECRET = "your_client_secret_here"
   USERNAME = "your_spotify_account_id"
   ```

## Usage
Simply update the `test_url` inside the `if __name__ == "__main__":` block with your desired Setlist.fm concert link, then run the script:

```bash
python script_name.py
```
*On the first run, a browser window will open asking you to authenticate with your Spotify account. Once authorized, copy the redirected URL from your browser's address bar and paste it into the terminal prompt.*

---
