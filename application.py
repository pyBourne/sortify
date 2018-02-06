#!/usr/bin/env python
# Copyright (C) 2018 Jacob Bourne


import json
import os
import urllib.parse
import redis
import datetime
from collections import namedtuple
from itertools import zip_longest

import requests
from dotenv import find_dotenv, load_dotenv
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)
from flask_bootstrap import Bootstrap
from flask_wtf import Form
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, NoneOf

from shuffler import Shuffler

from flask_kvsession import KVSessionExtension
from simplekv.memory.redisstore import RedisStore
from simplekv.decorator import PrefixDecorator
from spotify import Spotify, SpotifyToken, User

# set up a redis session cache
store = RedisStore(redis.StrictRedis())
prefixed_store = PrefixDecorator('sessions_', store)
# start the app
application = Flask(__name__)
# add the bootstrap
bootstrap = Bootstrap(application)
# create the serverside redis session
KVSessionExtension(store, application)

application.permanent_session_lifetime = datetime.timedelta(seconds=3600)

# load the .env file for local dev
load_dotenv(find_dotenv())
application.secret_key = os.environ.get("SecretKey")


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
        auth_url = Spotify.get_auth_url()
        return redirect(auth_url)
    else:
        spotify = Spotify(token=session['spotify_token'])
        session['spotify'] = spotify
        return redirect('playlists')


@application.route("/callback")
def callback():
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
    playlists = spotify.get_playlists()
    session["playlist_names"] = [playlist.name for playlist in playlists]
    session['user'] = user
    return render_template("playlists.html", playlists=playlists)



if __name__ == "__main__":
    load_dotenv(find_dotenv())
    application.secret_key = os.environ.get("SecretKey")
    application.run(debug=True)
