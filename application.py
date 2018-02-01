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
from collections import namedtuple

import spotipy
import spotipy.oauth2
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



PORT = os.environ.get('base_port')
if PORT is None:
    REDIRECT_URI = "{}/playlists".format(CLIENT_SIDE_URL)
else:
    REDIRECT_URI = "{}:{}/playlists".format(CLIENT_SIDE_URL, PORT)


SCOPE = ("playlist-modify-public playlist-modify-private "
         "playlist-read-collaborative playlist-read-private")

Results = namedtuple('Results', ['sort', 'script', 'div'])


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
    sp_oauth = get_oauth()
    return redirect(sp_oauth.get_authorize_url())


@application.route("/playlists")
def playlist_selection():
    """Render playlists as buttons to choose from."""
    # This is the route which the Spotify OAuth redirects to.
    # We finish getting an access token here.
    if request.args.get("code"):
        get_spotify(request.args["code"])

    playlists = get_user_playlists()
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


def get_oauth():
    """Return a Spotipy Oauth2 object."""
    print(REDIRECT_URI)
    return spotipy.oauth2.SpotifyOAuth(
        os.environ.get("ClientID"),
        os.environ.get("ClientSecret"),
        REDIRECT_URI, scope=SCOPE,
        cache_path=".tokens")


def get_spotify(auth_token=None):
    """Return an authenticated Spotify object."""
    oauth = get_oauth()
    token_info = oauth.get_cached_token()
    if not token_info and auth_token:
        token_info = oauth.get_access_token(auth_token)
    return spotipy.Spotify(token_info["access_token"])


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
    application.run(debug=bool(os.environ.get("debug")), port=PORT)
