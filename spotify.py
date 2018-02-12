#!/usr/bin/env python
# Copyright (C) 2018 Jacob Bourne


import datetime
import json
import logging
import os
import urllib.parse
from collections import namedtuple

import attr
import requests
from dateutil.relativedelta import relativedelta

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
USER_PROFILE_ENDPOINT = "{}/me".format(SPOTIFY_API_URL)
AUDIO_FEATURES_ENDPOINT = "{}/audio-features".format(SPOTIFY_API_URL)

PORT = os.environ.get('base_port')
if PORT is None:
    REDIRECT_URI = "{}/callback".format(CLIENT_SIDE_URL)
else:
    REDIRECT_URI = "{}:{}/callback".format(CLIENT_SIDE_URL, PORT)

SCOPE = ("playlist-modify-public playlist-modify-private "
         "playlist-read-collaborative playlist-read-private")

SpotifyToken = namedtuple(
    'SpotifyToken', ['access_token', 'refresh_token', 'token_type', 'expires_on'])


logger = logging.getLogger(__name__)

class Spotify(object):
    _access_token = None
    _refresh_token = None
    _token_type = None
    _expires_on = None

    _user = None

    def __init__(self, auth_code=None, token=None):

        if all(v is None for v in {auth_code, token}):
            raise ValueError('Expected either auth_code or token args')

        if token is None:
            self._logon(auth_code)

    def _logon(self, auth_code):
        logger.debug('Logging in with auth code')
        code_payload = {
            "grant_type": "authorization_code",
            "code": str(auth_code),
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        self._logon_or_refresh(code_payload)

    def _refresh(self):
        logger.debug('Refreshing tokens')
        code_payload = {
            "grant_type": "authorization_code",
            "code": str(self._refresh_token),
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        self._logon_or_refresh(code_payload)

    def _logon_or_refresh(self, payload):
        logger.debug('Getting Spotify Tokens')
        headers = {}
        post_request = requests.post(
            SPOTIFY_TOKEN_URL, data=payload, headers=headers)

        response_data = json.loads(post_request.text)
        self._access_token = response_data['access_token']
        self._refresh_token = response_data['refresh_token']
        self._token_type = response_data['token_type']
        seconds = int(response_data['expires_in'])
        self._expires_on = datetime.datetime.now() + relativedelta(seconds=seconds)

    def get_spotify_token(self):
        token = SpotifyToken(self._access_token,
                             self._refresh_token,
                             self._token_type,
                             self._expires_on)

    def isLive(self):
        if self._expires_on < datetime.datetime.now():
            self._logger.debug('Token expired, refreshing')
            self._refresh()
        return True

    def get_authorization_header(self):
        authorization_header = {"Authorization": "Bearer {}".format(self._access_token)}
        return authorization_header

    def get_user(self):
        self.isLive()
        profile_response = requests.get(
            USER_PROFILE_ENDPOINT, headers=self.get_authorization_header())
        profile_data = json.loads(profile_response.text)
        self._user = User(display_name=profile_data['display_name'],
                          href=profile_data['href'],
                          uri=profile_data['uri'],
                          id=profile_data['id'])
        logger.debug('Retrieved user {}'.format(profile_data['id']))
        return self._user

    def get_playlists(self):
        self.isLive()
        if self._user is None:
            # this really shouldnt happen
            self.get_user()
        playlist_api_endpoint = "{}/playlists".format(self._user.href)
        playlists_response = requests.get(
            playlist_api_endpoint, headers=self.get_authorization_header())
        playlist_data = json.loads(playlists_response.text)
        playlists = [self._create_playlist(x) for x in playlist_data['items']]
        while playlist_data['next']:
            playlists_response = requests.get(
                playlist_data['next'], headers=self.get_authorization_header())
            playlist_data = json.loads(playlists_response.text)
            playlists.extend([self._create_playlist(x) for x in playlist_data['items']])
        return playlists

    def get_playlist(self, playlist_url: str):
        self.isLive()
        playlist_response = requests.get(playlist_url, headers=self.get_authorization_header())
        playlist_data = json.loads(playlist_response.text)
        playlist = self._create_playlist(playlist_data)
        return playlist

    def get_playlist_tracks(self, playlist_url: str):
        self.isLive()
        tracks_url = '{}/tracks'.format(playlist_url)
        tracks_response = requests.get(tracks_url, headers=self.get_authorization_header())
        tracks_data = json.loads(tracks_response.text)

        track_info = tracks_data["items"]
        while tracks_data['next']:
            tracks_response = requests.get(tracks_data['next'], headers=self.get_authorization_header())
            tracks_data = json.loads(tracks_response.text)
            track_info.extend(tracks_data["items"])

        tracks = [self._create_track(x['track']) for x in track_info]
        return tracks

    def create_playlist(self, playlist_name):
        self.isLive()
        if self._user is None:
            # this really shouldnt happen
            self.get_user()

        create_api_endpoint = '{}/users/{}/playlists'.format(
            SPOTIFY_API_URL, self._user.id)

        code_payload = {
            "description": "Shuffled Playlist",
            "public": False,
            "name": playlist_name
        }

        response = requests.post(
            create_api_endpoint, json=code_payload, headers=self.get_authorization_header())
        response_data = json.loads(response.text)
        logger.debug('Created playlist {}'.format(playlist_name))
        return response_data['id']

    def add_tracks_to_playlist(self, playlist_id: str, tracks):
        self.isLive()
        if self._user is None:
            # this really shouldnt happen
            self.get_user()

        add_api_endpoint = '{}/users/{}/playlists/{}/tracks'.format(
            SPOTIFY_API_URL, self._user.id, playlist_id)

        # can only add in groups of 100
        track_groups = [tracks[i:i + 100] for i in range(0, len(tracks), 100)]

        for track_group in track_groups:
            uris = [x.uri for x in track_group]
            response = requests.post(add_api_endpoint, json={'uris': uris},
                                     headers=self.get_authorization_header())

    def get_audio_features(self, tracks):
        self.isLive()

        if not isinstance(tracks, list):
            tracks = [tracks]

        # can get up to 100 at a time
        track_groups = [tracks[i:i + 100] for i in range(0, len(tracks), 100)]

        track_data = []
        for track_group in track_groups:
            payload = {'ids': ','.join([x.id for x in track_group])}
            response = requests.get(AUDIO_FEATURES_ENDPOINT, params=payload, headers=self.get_authorization_header())
            response_data = json.loads(response.text)
            track_data.extend(response_data['audio_features'])

        return track_data

    @staticmethod
    def _create_playlist(playlist_data):
        playlist = Playlist(href=playlist_data['href'],
                            id=playlist_data['id'],
                            name=playlist_data['name'],
                            uri=playlist_data['uri'],
                            images=playlist_data['images'],
                            tracks=playlist_data['tracks'])
        return playlist

    @staticmethod
    def _create_track(track_data):
        track = Track(href=track_data['href'],
                      id=track_data['id'],
                      name=track_data['name'],
                      uri=track_data['uri'],
                      popularity=track_data['popularity'])
        return track

    @staticmethod
    def get_auth_url():
        auth_query_parameters = {
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "client_id": CLIENT_ID
        }
        url_args = "&".join(["{}={}".format(key, urllib.parse.quote(val))
                             for key, val in auth_query_parameters.items()])
        auth_url = "{}/?{}".format(SPOTIFY_AUTH_URL, url_args)
        return auth_url


@attr.s(frozen=True)
class User(object):
    display_name = attr.ib(validator=attr.validators.instance_of(str), type=str)
    href = attr.ib(validator=attr.validators.instance_of(str), type=str)
    uri = attr.ib(validator=attr.validators.instance_of(str), type=str)
    id = attr.ib(validator=attr.validators.instance_of(str), type=str)


@attr.s(frozen=True)
class Playlist(object):
    href = attr.ib(validator=attr.validators.instance_of(str), type=str)
    id = attr.ib(validator=attr.validators.instance_of(str), type=str)
    name = attr.ib(validator=attr.validators.instance_of(str), type=str)
    uri = attr.ib(validator=attr.validators.instance_of(str), type=str)
    images = attr.ib(validator=attr.validators.instance_of(list))
    tracks = attr.ib(validator=attr.validators.instance_of(dict))


@attr.s(frozen=True)
class Track(object):
    href = attr.ib(validator=attr.validators.instance_of(str), type=str)
    id = attr.ib(validator=attr.validators.instance_of(str), type=str)
    name = attr.ib(validator=attr.validators.instance_of(str), type=str)
    uri = attr.ib(validator=attr.validators.instance_of(str), type=str)
    popularity = attr.ib(converter=int, validator=attr.validators.instance_of(int), type=int)
