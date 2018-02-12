#!/usr/bin/env python
# Copyright (C) 2018 Jacob Bourne


import datetime
import logging
import os
from collections import namedtuple

import redis
from dotenv import find_dotenv, load_dotenv
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)
from flask_bootstrap import Bootstrap
from flask_kvsession import KVSessionExtension
from flask_mobility import Mobility
from flask_wtf import Form
from simplekv.decorator import PrefixDecorator
from simplekv.memory.redisstore import RedisStore
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, NoneOf

from shuffler import Shuffler
from spotify import Spotify

# just an easy holder
Results = namedtuple('Results', ['sort', 'script', 'div'])

# load the .env file for local dev
load_dotenv(find_dotenv())

# set up a redis session cache
redis_host = os.environ.get('redis_host')
redis_port = int(os.environ.get('redis_port'))
store = RedisStore(redis.StrictRedis(host=redis_host, port=redis_port))
prefixed_store = PrefixDecorator('sessions_', store)
# start the app
application = Flask(__name__)
# add the bootstrap
bootstrap = Bootstrap(application)
# add mobility
Mobility(application)
# create the serverside redis session
KVSessionExtension(store, application)
application.permanent_session_lifetime = datetime.timedelta(seconds=3600)

# set the secret key
application.secret_key = os.environ.get("SecretKey")

# set up logging
if os.environ.get('debug') != 'True':
    logging.basicConfig(filename='/opt/python/log/spotify.log', level=logging.INFO)


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


@application.route("/about")
def about():
    return render_template('about.html')


@application.route("/login")
def login():
    session.permanent = True
    if session.get('spotify_token') is None:
        application.logger.debug('No spotify token in session, resigning in')
        auth_url = Spotify.get_auth_url()
        return redirect(auth_url)
    else:
        application.logger.debug('Reloading spotify token from session')
        spotify = Spotify(token=session['spotify_token'])
        session['spotify'] = spotify
        return redirect('playlists')


@application.route("/callback")
def callback():
    application.logger.debug('Returning from callback')
    auth_token = request.args['code']
    spotify = Spotify(auth_code=auth_token)
    session['spotify'] = spotify
    session['spotify_token'] = spotify.get_spotify_token()
    return redirect('playlists')


@application.route("/playlists")
def playlist_selection():
    if session.get('spotify') is None:
        return redirect('playlists')

    spotify = session['spotify']
    user = spotify.get_user()
    application.logger.info('User {} logged in, name={}'.format(user.id, user.display_name))
    playlists = spotify.get_playlists()
    session["playlist_names"] = [playlist.name for playlist in playlists]
    session["playlist_url"] = {x.id: x.href for x in playlists}
    session['user'] = user
    return render_template("playlists.html", playlists=playlists)


@application.route("/playlist/<playlist_id>", methods=["GET", "POST"])
def view_playlist(playlist_id):
    """Shuffle a playlist and allow user to save to a new playlist."""
    form = PlaylistNameForm(session["playlist_names"])
    spotify = session['spotify']
    playlist_urls = session['playlist_url']
    playlist_url = playlist_urls[playlist_id]

    playlist = spotify.get_playlist(playlist_url)
    tracks = spotify.get_playlist_tracks(playlist_url)
    application.logger.info('Sorting playlist {} at {}'.format(playlist.name, playlist.uri))

    if "Shuffle" in request.form:
        return redirect(url_for("view_playlistsplaylist", playlist_id=playlist_id))
    elif form.validate_on_submit():
        new_playlist_name = form.name.data
        new_playlist_id = spotify.create_playlist(new_playlist_name)
        # You can add up to 100 tracks per request.
        spotify.add_tracks_to_playlist(new_playlist_id, session['shuffled'])
        application.logger.info('Saving playlist {}'.format(new_playlist_name))
        flash("Playlist '{}' saved.".format(new_playlist_name))
        return redirect(url_for("playlist_selection"))

    name = session["name"] = playlist.name
    images = playlist.images[1] if len(playlist.images) > 1 else playlist.images[-1]
    shuffle = smart_shuffle(tracks)
    session["shuffled"] = [tracks[x] for x in shuffle.sort]
    track_names = [x.name for x in tracks]
    shuffled_names = [x.name for x in session["shuffled"]]

    return render_template(
        "playlist.html", name=name, track_names=track_names,
        shuffled_names=shuffled_names, images=images, form=form,
        script=shuffle.script, div=shuffle.div)


def smart_shuffle(tracks):
    spotify = session['spotify']
    features = spotify.get_audio_features(tracks)
    shuffler = Shuffler(tracks, features)
    sort = shuffler.get_sort()
    script, div = shuffler.get_charts(request.MOBILE)
    results = Results(sort=tuple(sort), script=script, div=div)
    return results


if __name__ == "__main__":
    load_dotenv(find_dotenv())
    application.secret_key = os.environ.get("SecretKey")
    application.run(debug=True)
