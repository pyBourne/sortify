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


import os
import requests
import base64
import urllib.parse
import json
from collections import namedtuple

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
    url_args = "&".join(["{}={}".format(key,urllib.parse.quote(val)) for key,val in auth_query_parameters.items()])
    auth_url = "{}/?{}".format(SPOTIFY_AUTH_URL, url_args)
    return redirect(auth_url)



@application.route("/playlists")
def playlist_selection():
    # Auth Step 4: Requests refresh and access tokens
    auth_token = request.args['code']
    code_payload = {
        "grant_type": "authorization_code",
        "code": str(auth_token),
        "redirect_uri": REDIRECT_URI,
        "client_id" : CLIENT_ID,
        "client_secret" : CLIENT_SECRET
    }
    headers = {}
    post_request = requests.post(SPOTIFY_TOKEN_URL, data=code_payload, headers=headers)

    # Auth Step 5: Tokens are Returned to Application
    response_data = json.loads(post_request.text)
    access_token = response_data["access_token"]
    refresh_token = response_data["refresh_token"]
    token_type = response_data["token_type"]
    expires_in = response_data["expires_in"]

    # Auth Step 6: Use the access token to access Spotify API
    authorization_header = {"Authorization":"Bearer {}".format(access_token)}

    # Get profile data
    user_profile_api_endpoint = "{}/me".format(SPOTIFY_API_URL)
    profile_response = requests.get(user_profile_api_endpoint, headers=authorization_header)
    profile_data = json.loads(profile_response.text)

    # Get user playlist data
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

    spotify = get_spotify()
    user_id = spotify.current_user()["id"]
    results = spotify.user_playlist(user_id, playlist_id)

    tracks = results["tracks"]
    track_info = tracks["items"]
    # Spotify returns results in a pager; get next results if more than
    # 100 returned.
    while tracks["next"]:
        tracks = spotify.next(tracks)
        track_info.extend(tracks["items"])

    track_names = [(track["track"]["name"], track["track"]["id"]) for track in
                   track_info]

    if "Shuffle" in request.form:
        return redirect(url_for("view_playlistsplaylist", playlist_id=playlist_id))
    elif form.validate_on_submit():
        new_playlist_name = form.name.data
        spotify.user_playlist_create(user_id, new_playlist_name,
                                     public=results["public"])
        new_playlist_id = get_playlist_id_by_name(new_playlist_name)
        # You can add up to 100 tracks per request.
        all_tracks = [track_names[item][1] for item in session["shuffled"] if
                      track_names[item][1] is not None]
        for tracks in get_tracks_for_add(all_tracks):
            spotify.user_playlist_add_tracks(user_id, new_playlist_id, tracks)
        flash("Playlist '{}' saved.".format(new_playlist_name))
        return redirect(url_for("playlists"))

    name = session["name"] = results["name"]
    images = results["images"]
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
    spotify = get_spotify()
    shuffler = Shuffler(tracks, spotify)
    sort = shuffler.get_sort()
    script, div = shuffler.get_charts()
    results = Results(sort=tuple(sort), script=script, div=div)

    return results


def get_names(tracks):
    """Return just the name component of a list of name/id tuples."""
    return [track[0] for track in tracks]


def get_user_playlists():
    """Return an id, name, images tuple of a user's playlists."""
    spotify = get_spotify()
    user_id = spotify.current_user()["id"]
    results = spotify.user_playlists(user_id)

    playlists = results["items"]
    while results["next"]:
        results = spotify.next(results)
        playlists.extend(results["items"])

    playlist_names = [{"id": playlist["id"], "name": playlist["name"],
                       "images": playlist["images"]} for playlist in playlists]
    return playlist_names


def get_playlist_id_by_name(name):
    """Return the id for a playlist with name: 'name'."""
    return [playlist["id"] for playlist in get_user_playlists() if
            playlist["name"] == name][0]


if __name__ == "__main__":
    load_dotenv(find_dotenv())
    application.secret_key = os.environ.get("SecretKey")
    application.run(debug=bool(os.environ.get("debug")), port=int(PORT))
