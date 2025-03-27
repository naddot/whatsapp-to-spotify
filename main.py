import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import re
import os
import zipfile
import io

# === Set environment variables using Streamlit secrets ===
os.environ['SPOTIPY_CLIENT_ID'] = st.secrets["SPOTIPY_CLIENT_ID"]
os.environ['SPOTIPY_CLIENT_SECRET'] = st.secrets["SPOTIPY_CLIENT_SECRET"]
os.environ['SPOTIPY_REDIRECT_URI'] = st.secrets["SPOTIPY_REDIRECT_URI"]

# === Spotify Scope ===
SCOPE = 'playlist-modify-public playlist-modify-private'

# === Authenticate User ===
def authenticate_user():
    auth_manager = SpotifyOAuth(scope=SCOPE)
    sp = spotipy.Spotify(auth_manager=auth_manager)
    return sp

# === Get or create playlist ===
def get_or_create_playlist(sp, user_id, playlist_name):
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        if playlist['name'].lower() == playlist_name.lower():
            return playlist['id'], False
    new_playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=True)
    return new_playlist['id'], True

# === Get existing track IDs in a playlist ===
def get_existing_track_ids(sp, playlist_id):
    existing_ids = []
    results = sp.playlist_items(playlist_id)
    while results:
        existing_ids.extend([item['track']['id'] for item in results['items'] if item['track']])
        if results['next']:
            results = sp.next(results)
        else:
            break
    return set(existing_ids)

# === Extract Spotify Track URLs from WhatsApp text ===
def extract_spotify_track_ids(text):
    urls = re.findall(r'https://open\.spotify\.com/track/[a-zA-Z0-9]+', text)
    return list(set([url.split('/')[-1].split('?')[0] for url in urls]))

# === Streamlit UI ===
st.set_page_config(page_title="WhatsApp to Spotify", layout="centered")

st.title("📲 WhatsApp to Spotify Playlist")

st.markdown("Upload a WhatsApp chat export (.zip or .txt) and we'll add all the Spotify songs to a playlist in your account.")

with st.expander("ℹ️ How to export a WhatsApp chat (.txt file)"):
    st.markdown("""
    **📱 On iPhone:**
    1. 📂 Open WhatsApp > the chat you want to export
    2. 👤 Tap the contact's name or group title
    3. 📤 Tap **Export Chat** > Choose **Without Media**
    4. 💾 Save to **Files** > Select a location you'll remember

    **🤖 On Android:**
    1. 📂 Open WhatsApp > the chat you want to export
    2. ⋮ Tap the 3 dots in the top right > **More** > **Export Chat**
    3. 📤 Choose **Without Media**
    4. 💾 Save to your phone or Google Drive

    ⚠️ Note: WhatsApp may export your chat as a `.zip` file. This app will automatically extract the `.txt` file for you.
    """)

uploaded_file = st.file_uploader("📎 Upload WhatsApp .zip or .txt File", type=["txt", "zip"])
playlist_name = st.text_input("🎶 Playlist Name", value="WhatsApp Songs")

if st.button("🚀 Create / Update Playlist"):
    if not uploaded_file:
        st.error("❌ Please upload a WhatsApp chat file (.zip or .txt).")
    elif not playlist_name.strip():
        st.error("❌ Please enter a playlist name.")
    else:
        try:
            sp = authenticate_user()
            user_id = sp.me()['id']

            # === Read uploaded content ===
            if uploaded_file.name.endswith(".zip"):
                with zipfile.ZipFile(uploaded_file) as z:
                    txt_files = [f for f in z.namelist() if f.endswith(".txt")]
                    if not txt_files:
                        st.error("❌ No .txt file found in the .zip archive.")
                        st.stop()
                    with z.open(txt_files[0]) as txt_file:
                        chat_text = txt_file.read().decode('utf-8')
            else:
                chat_text = uploaded_file.read().decode('utf-8')

            track_ids = extract_spotify_track_ids(chat_text)
            if not track_ids:
                st.warning("⚠️ No Spotify track links found in the file.")
            else:
                playlist_id, created = get_or_create_playlist(sp, user_id, playlist_name)
                existing_ids = get_existing_track_ids(sp, playlist_id)

                new_tracks = [tid for tid in track_ids if tid not in existing_ids]

                if new_tracks:
                    for i in range(0, len(new_tracks), 100):
                        sp.playlist_add_items(playlist_id, new_tracks[i:i+100])
                    st.success(f"✅ Added {len(new_tracks)} new tracks to '{playlist_name}'!")
                else:
                    st.info("ℹ️ All songs from the file are already in the playlist.")

                playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
                st.markdown(f"[🎵 View Playlist on Spotify]({playlist_url})")
                st.info("✅ Your chat has been processed. You can now safely delete the uploaded file from your phone.")

        except Exception as e:
            st.error(f"❌ Something went wrong: {e}")
