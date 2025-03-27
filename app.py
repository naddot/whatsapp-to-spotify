import os
import zipfile
import re
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth

app = Flask(__name__)
app.secret_key = 'your-secret-key'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Set environment variables (use dotenv or set them securely for production)
os.environ['SPOTIPY_CLIENT_ID'] = 'your-client-id'
os.environ['SPOTIPY_CLIENT_SECRET'] = 'your-client-secret'
os.environ['SPOTIPY_REDIRECT_URI'] = 'http://localhost:5000/callback'

SCOPE = 'playlist-modify-public playlist-modify-private'

def extract_spotify_track_ids(text):
    urls = re.findall(r'https://open\.spotify\.com/track/[a-zA-Z0-9]+', text)
    return list(set([url.split('/')[-1].split('?')[0] for url in urls]))

def get_or_create_playlist(sp, user_id, playlist_name):
    playlists = sp.current_user_playlists(limit=50)
    for playlist in playlists['items']:
        if playlist['name'].lower() == playlist_name.lower():
            return playlist['id'], False
    new_playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=True)
    return new_playlist['id'], True

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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        playlist_name = request.form.get('playlist_name', '').strip()
        file = request.files.get('chat_file')

        if not file or not playlist_name:
            flash("Please provide both a playlist name and a file.")
            return redirect(url_for('index'))

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        if filename.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]
                if not txt_files:
                    flash("No .txt file found in the .zip archive.")
                    return redirect(url_for('index'))
                with zip_ref.open(txt_files[0]) as txt_file:
                    chat_text = txt_file.read().decode('utf-8')
        elif filename.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                chat_text = f.read()
        else:
            flash("Unsupported file format. Upload a .zip or .txt file.")
            return redirect(url_for('index'))

        track_ids = extract_spotify_track_ids(chat_text)
        if not track_ids:
            flash("No Spotify track links found in the file.")
            return redirect(url_for('index'))

        sp = Spotify(auth_manager=SpotifyOAuth(scope=SCOPE))
        user_id = sp.me()['id']

        playlist_id, created = get_or_create_playlist(sp, user_id, playlist_name)
        existing_ids = get_existing_track_ids(sp, playlist_id)
        new_tracks = [tid for tid in track_ids if tid not in existing_ids]

        if new_tracks:
            for i in range(0, len(new_tracks), 100):
                sp.playlist_add_items(playlist_id, new_tracks[i:i+100])
            flash(f"Added {len(new_tracks)} tracks to '{playlist_name}'.")
        else:
            flash("All songs from the file are already in the playlist.")

        return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True)
