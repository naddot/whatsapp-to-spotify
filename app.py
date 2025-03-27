import os
import zipfile
import re
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import json 
from werkzeug.utils import secure_filename
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from zipfile import is_zipfile


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

os.environ['SPOTIPY_CLIENT_ID'] = os.getenv("SPOTIPY_CLIENT_ID")
os.environ['SPOTIPY_CLIENT_SECRET'] = os.getenv("SPOTIPY_CLIENT_SECRET")
os.environ['SPOTIPY_REDIRECT_URI'] = os.getenv("SPOTIPY_REDIRECT_URI")

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
    authenticated = 'token_info' in session

    # Load billboard data
    top_playlists = []
    billboard_path = os.path.join('static', 'billboard.json')
    if os.path.exists(billboard_path):
        with open(billboard_path, 'r') as f:
            data = json.load(f)
            top_playlists = sorted(data, key=lambda x: (-x['followers'], x['timestamp']))[:3]

    if request.method == 'GET':
        if 'shared' in request.args:
            flash("🎉 Your playlist was created and shared to the Billboard!")

        return render_template(
            'index.html',
            authenticated=authenticated,
            show_billboard=True,
            top_playlists=top_playlists
        )

    # POST method (form submission)
    playlist_name = request.form.get('playlist_name', '').strip()
    file = request.files.get('chat_file')

    if not file or not playlist_name:
        flash("Please provide both a playlist name and a file.")
        return redirect(url_for('index'))

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    if is_zipfile(file_path):
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
    try:
        os.remove(file_path)
    except Exception as e:
        print(f"⚠️ Could not delete file {file_path}: {e}")
    if not track_ids:
        flash("No Spotify track links found in the file.")
        return redirect(url_for('index'))

    sp_oauth = SpotifyOAuth(scope=SCOPE)
    session.pop('token_info', None)
    flash("Please log in with Spotify to continue.")
    return redirect(sp_oauth.get_authorize_url())

    sp = Spotify(auth=token_info['access_token'])
    user_id = sp.me()['id']

    playlist_id, created = get_or_create_playlist(sp, user_id, playlist_name)
    existing_ids = get_existing_track_ids(sp, playlist_id)
    new_tracks = [tid for tid in track_ids if tid not in existing_ids]

    if new_tracks:
        for i in range(0, len(new_tracks), 100):
            sp.playlist_add_items(playlist_id, new_tracks[i:i+100])
        flash(f"Added {len(new_tracks)} tracks to '{playlist_name}'.")
        flash(f"✅ Playlist updated! <a href='https://open.spotify.com/playlist/{playlist_id}' target='_blank'>View it on Spotify</a>.")
    else:
        flash("All songs from the file are already in the playlist.")

    return render_template('share_prompt.html', playlist_id=playlist_id)
    

@app.route('/connect')
def connect():
    sp_oauth = SpotifyOAuth(scope=SCOPE)
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = SpotifyOAuth(scope=SCOPE)
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)

    if not token_info:
        flash("Failed to get access token from Spotify.")
        return redirect(url_for('index'))

    session['token_info'] = token_info
    flash("Spotify authentication successful.")
    return redirect(url_for('index'))

@app.route('/share', methods=['POST'])
def share():
    playlist_id = request.form.get('playlist_id')
    token_info = session.get('token_info')

    if not playlist_id or not token_info:
        flash("Missing playlist or session. Please try again.")
        return redirect(url_for('index'))

    sp = Spotify(auth=token_info['access_token'])
    playlist = sp.playlist(playlist_id)

    name = playlist['name']
    url = playlist['external_urls']['spotify']
    followers = playlist['followers']['total']
    cover = playlist['images'][0]['url'] if playlist['images'] else ''

    billboard_entry = {
        'id': playlist_id,
        'name': name,
        'url': url,
        'followers': followers,
        'cover': cover,
        'timestamp': str(datetime.utcnow())
    }

    billboard_path = os.path.join('static', 'billboard.json')
    if os.path.exists(billboard_path):
        with open(billboard_path, 'r') as f:
            billboard = json.load(f)
    else:
        billboard = []

    # Add and dedupe by playlist ID
    # Refresh follower counts for all entries
    updated_billboard = []
    for entry in billboard:
        try:
            data = sp.playlist(entry['id'])
            entry['followers'] = data['followers']['total']
            updated_billboard.append(entry)
        except Exception as e:
            print(f"⚠️ Failed to update playlist {entry['id']}: {e}")

    # Add and dedupe new one
    updated_billboard = [b for b in updated_billboard if b['id'] != playlist_id]
    updated_billboard.append(billboard_entry)
    billboard = updated_billboard

    
    with open(billboard_path, 'w') as f:
        json.dump(billboard, f, indent=2)

    return redirect(url_for('index', shared=True))


@app.route('/billboard')
def billboard():
    billboard_path = os.path.join('static', 'billboard.json')
    if not os.path.exists(billboard_path):
        playlists = []
    else:
        with open(billboard_path, 'r') as f:
            playlists = json.load(f)

    playlists.sort(key=lambda p: (-p['followers'], p['timestamp']))
    return render_template('billboard.html', playlists=playlists)


if __name__ == '__main__':
    app.run(debug=True)
