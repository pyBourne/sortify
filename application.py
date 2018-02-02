#!/usr/bin/env python
# Copyright (C) 2018 Jacob Bourne
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import json
import os
import urllib.parse
from collections import namedtuple
from itertools import zip_longest

import requests
from dotenv import load_dotenv, find_dotenv
from flask import (Flask, request, redirect, render_template, url_for,
                   session, flash)
from flask_bootstrap import Bootstrap
from flask_wtf import Form
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, NoneOf

from shuffler import Shuffler

application = Flask(__name__)
bootstrap = Bootstrap(application)
load_dotenv(find_dotenv())
application.secret_key = os.environ.get("SecretKey")

# Flask Parameters
CLIENT_SIDE_URL = os.environ.get('base_url')

#  Client Keys
CLIENT_ID = os.environ.get('ClientID')
CLIENT_SECRET = os.environ.get('ClientSecret')

# Spotify URLS
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE_URL = "https://api.spotify.com"
API_VERSION = "v1"
SPOTIFY_API_URL = "{}/{}".format(SPOTIFY_API_BASE_URL, API_VERSION)

PORT = os.environ.get('base_port')
if PORT is None:
    REDIRECT_URI = "{}/playlists".format(CLIENT_SIDE_URL)
else:
    REDIRECT_URI = "{}:{}/playlists".format(CLIENT_SIDE_URL, PORT)

SCOPE = ("playlist-modify-public playlist-modify-private "
         "playlist-read-collaborative playlist-read-private")

Results = namedtuple('Results', ['sort', 'script', 'div'])
SpotifyToken = namedtuple('SpotifyToken', ['access_token', 'refresh_token', 'token_type', 'expires_in'])

auth_query_parameters = {
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPE,
    # "state": STATE,
    # "show_dialog": SHOW_DIALOG_str,
    "client_id": CLIENT_ID
}


class PlaylistNameForm(Form):
    """Form for getting new playlist name.

    Will not accept existing playlist names.
    """
    name = StringField("Playlist Name", validators=[DataRequired()])
    submit = SubmitField("Save")

    def __init__(self, playlist_names):
        super(PlaylistNameForm, self).__init__()
        self.name.validators.append(
            NoneOf(playlist_names, message="That name is already in use!"))


@application.route("/")
def index():
    return render_template('landing.html')


@application.route("/login")
def login():
    # Auth Step 1: Authorization
    url_args = "&".join(["{}={}".format(key, urllib.parse.quote(val)) for key, val in auth_query_parameters.items()])
    auth_url = "{}/?{}".format(SPOTIFY_AUTH_URL, url_args)
    return redirect(auth_url)


@application.route("/playlists")
def playlist_selection():

    if session['spotify_token'] is None:
        # Auth Step 4: Requests refresh and access tokens
        auth_token = request.args['code']
        code_payload = {
            "grant_type": "authorization_code",
            "code": str(auth_token),
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        headers = {}
        post_request = requests.post(SPOTIFY_TOKEN_URL, data=code_payload, headers=headers)

        # Auth Step 5: Tokens are Returned to Application
        response_data = json.loads(post_request.text)
        spotify_token = {'access_token': response_data["access_token"],
                         'refresh_token': response_data["refresh_token"],
                         'token_type': response_data["token_type"],
                         'expires_in': response_data["expires_in"]}

        session['spotify_token'] = spotify_token

    spotify_token = session['spotify_token']
    # Auth Step 6: Use the access token to access Spotify API
    authorization_header = {"Authorization": "Bearer {}".format(spotify_token['access_token'])}

    # Get profile data
    user_profile_api_endpoint = "{}/me".format(SPOTIFY_API_URL)
    profile_response = requests.get(user_profile_api_endpoint, headers=authorization_header)
    profile_data = json.loads(profile_response.text)
    session['user_id'] = profile_data['id']

    # Get user plafrom flask_oauth import OAuthylist data
    playlist_api_endpoint = "{}/playlists".format(profile_data["href"])
    playlists_response = requests.get(playlist_api_endpoint, headers=authorization_header)
    playlist_data = json.loads(playlists_response.text)

    playlists = [{"id": playlist["id"], "name": playlist["name"],
                  "images": playlist["images"]} for playlist in playlist_data['items']]

    session["playlist_names"] = [playlist["name"] for playlist in playlists]
    return render_template("playlists.html", playlists=playlists)


@application.route("/playlist/<playlist_id>", methods=["GET", "POST"])
def view_playlist(playlist_id):
    """Shuffle a playlist and allow user to save to a new playlist."""
    form = PlaylistNameForm(session["playlist_names"])

    spotify_token = session['spotify_token']
    authorization_header = {"Authorization": "Bearer {}".format(spotify_token['access_token'])}
    playlist_api_endpoint = "{}/users/{}/playlists/{}".format(SPOTIFY_API_URL, session['user_id'], playlist_id)
    tracks_api_endpoint = "{}/tracks".format(playlist_api_endpoint)

    playlist_response = requests.get(playlist_api_endpoint, headers=authorization_header)
    tracks_reponse = requests.get(tracks_api_endpoint, headers=authorization_header)

    playlist_data = json.loads(playlist_response.text)
    results = json.loads(tracks_reponse.text)

    track_info = results["items"]
    # Spotify returns results in a pager; get next results if more than
    # 100 returned.
    # while tracks["next"]:
    # tracks = spotify.next(tracks)
    # track_info.extend(tracks["items"])

    track_names = [(track["track"]["name"], track["track"]["id"]) for track in
                   track_info]

    if "Shuffle" in request.form:
        return redirect(url_for("view_playlistsplaylist", playlist_id=playlist_id))
    elif form.validate_on_submit():
        new_playlist_name = form.name.data
        new_playlist_id = create_playlist(new_playlist_name)
        # You can add up to 100 tracks per request.
        all_tracks = [track_names[item][1] for item in session["shuffled"] if
                      track_names[item][1] is not None]
        for tracks in get_tracks_for_add(all_tracks):
            add_tracks(new_playlist_id, tracks)
        flash("Playlist '{}' saved.".format(new_playlist_name))
        return redirect(url_for("playlist_selection"))

    name = session["name"] = playlist_data["name"]
    images = playlist_data["images"]
    shuffle = smart_shuffle(track_names)
    session["shuffled"] = shuffle.sort
    shuffled_names = [track_names[idx] for idx in session["shuffled"]]

    return render_template(
        "playlist.html", name=name, track_names=get_names(track_names),
        shuffled_names=get_names(shuffled_names), images=images, form=form,
        script=shuffle.script, div=shuffle.div)


def get_tracks_for_add(tracks):
    """Break list of tracks into 100 track lists.

    This is a generator, so you can iterate over it.

    Args:
        tracks: List of track name/id/images tuples.
    Returns:
        List of 100 or less tracks.
    Raises:
        StopIteration when tracks are consumed.
    """
    idx = 0
    output = []
    while idx < len(tracks):
        output.append(tracks[idx])
        if len(output) == 100 or idx == len(tracks) - 1:
            yield output
            output = []
        idx += 1


def create_playlist(playlist_name):
    spotify_token = session['spotify_token']

    # Auth Step 6: Use the access token to access Spotify API
    authorization_header = {"Authorization": "Bearer {}".format(spotify_token['access_token']),
                            'Content-Type': 'application/json'}
    create_api_endpoint = '{}/users/{}/playlists'.format(SPOTIFY_API_URL, session['user_id'])

    code_payload = {
        "description": "Shuffled Playlist",
        "public": False,
        "name": playlist_name
    }

    response = requests.post(create_api_endpoint, json=code_payload, headers=authorization_header)
    response_data = json.loads(response.text)
    return response_data['id']


def add_tracks(playlist_id, tracks):
    spotify_token = session['spotify_token']
    user_id = session['user_id']
    authorization_header = {"Authorization": "Bearer {}".format(spotify_token['access_token'])}

    add_api_endpoint = '{}/users/{}/playlists/{}/tracks'.format(SPOTIFY_API_URL, user_id, playlist_id)
    uris = ['spotify:track:{}'.format(x) for x in tracks]
    response = requests.post(add_api_endpoint, json={'uris': uris}, headers=authorization_header)
    print(response.text)


def smart_shuffle(tracks):
    """Return a shuffling sequence. The sequence will be based on the traveling salesman
    problem once the music attributes space has been shifted into 2d space

    Because we can't fit large playlists into the session cookie, we
    only store a shuffling pattern, i.e. a sequence of indices.

    Args:
        tracks: An iterable.

    Returns:
        A tuple of shuffled indexes.
    """

    ids = [x[1] for x in tracks]
    spotify_token = session['spotify_token']
    authorization_header = {"Authorization": "Bearer {}".format(spotify_token['access_token'])}

    features = []

    for id in ids:
        features_api_endpoint = '{}/audio-features/{}'.format(SPOTIFY_API_URL, id)
        features_response = requests.get(features_api_endpoint, headers=authorization_header)
        features_data = json.loads(features_response.text)
        features.append(features_data)

    shuffler = Shuffler(tracks, features)
    sort = shuffler.get_sort()
    script, div = shuffler.get_charts()
    results = Results(sort=tuple(sort), script=script, div=div)

    return results


def get_names(tracks):
    """Return just the name component of a list of name/id tuples."""
    return [track[0] for track in tracks]


def get_playlist_id_by_name(name):
    """Return the id for a playlist with name: 'name'."""
    return [playlist["id"] for playlist in get_user_playlists() if
            playlist["name"] == name][0]


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


if __name__ == "__main__":
    load_dotenv(find_dotenv())
    application.secret_key = os.environ.get("SecretKey")
    application.run(debug=bool(os.environ.get("debug")), port=int(PORT))
