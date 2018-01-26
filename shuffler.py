#!/usr/bin/env python
# Copyright (C) 2016 Shea G Craig
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


import numpy as np
import pandas as pd
import sklearn.manifold as mani

import spotipy
import math

from ortools.constraint_solver import pywrapcp
from ortools.constraint_solver import routing_enums_pb2
from bokeh.plotting import figure, ColumnDataSource
from bokeh.embed import components
from bokeh.models import HoverTool

from typing import List, Tuple


class Shuffler(object):
    _tracks = []
    _spotify = None
    _df = None
    _sort = None
    _locations = None

    def __init__(self, tracks: List[tuple], spotify: spotipy):
        self._tracks = tracks
        self._spotify = spotify

    def _build_frame(self):
        ids = [x[1] for x in self._tracks]

        features = self._spotify.audio_features(ids)
        self._df = pd.DataFrame.from_dict(features)
        self._df.set_index('id')

    def get_features(self):
        if self._df is None:
            self._build_frame()

        f_cols = ['danceability', 'energy', 'key', 'loudness',
                  'speechiness', 'acousticness', 'instrumentalness',
                  'liveness', 'valence', 'tempo']

        return self._df[f_cols].values

    def decompose(self):
        if self._locations is None:
            tsne = mani.TSNE(n_components=2)
            self._locations = tsne.fit_transform(self.get_features())

        return self._locations

    def get_sort(self):
        if self._sort is None:
            self._sort = []
            locations = self.decompose()
            tsp_size = len(locations)
            num_routes = 1  # The number of routes, which is 1 in the TSP.
            # Nodes are indexed from 0 to tsp_size - 1. The depot is the starting node of the route.
            depot = 0
            # Create routing model.
            if tsp_size > 0:
                routing = pywrapcp.RoutingModel(tsp_size, num_routes, depot)
                search_parameters = pywrapcp.RoutingModel.DefaultSearchParameters()

                # Callback to the distance function. The callback takes two
                # arguments (the from and to node indices) and returns the distance between them.
                dist_between_locations = CreateDistanceCallback(locations)
                dist_callback = dist_between_locations.Distance
                routing.SetArcCostEvaluatorOfAllVehicles(dist_callback)
                # Solve, returns a solution if any.
                assignment = routing.SolveWithParameters(search_parameters)
                if assignment:

                    # Solution cost.
                    print("Total distance: {}".format(assignment.ObjectiveValue()))

                    # Inspect solution.
                    # Only one route here; otherwise iterate from 0 to routing.vehicles() - 1.
                    route_number = 0
                    node = routing.Start(route_number)
                    start_node = node
                    route = ''

                    while not routing.IsEnd(node):
                        self._sort.append(node)
                        node = assignment.Value(routing.NextVar(node))

        return self._sort

    def get_charts(self):
        if self._sort is None:
            self.get_sort()


        old_names = [x[0] for x in self._tracks]
        sorted_names = [old_names[i] for i in self._sort]

        locs = np.array(self._locations)
        sorted_locs = np.array([locs[i] for i in self._sort])

        old_source = ColumnDataSource(data=dict(
            x=locs[:,0],
            y=locs[:,1],
            name=old_names,
        ))

        new_source = ColumnDataSource(data=dict(
            x=sorted_locs[:,0],
            y=sorted_locs[:,1],
            name=sorted_names,
        ))

        hover = HoverTool(tooltips=[
            ("name", "@name"),
            ("(x,y)", "($x, $y)"),
        ])

        p_orig = figure(plot_width=400, plot_height=400, tools=[hover])
        p_sort = figure(plot_width=400, plot_height=400, tools=[hover])

        #add the circles
        p_orig.circle('x', 'y', size=5, color="navy", alpha=0.5, source=old_source)
        p_sort.circle('x', 'y', size=5, color="navy", alpha=0.5, source=new_source)

        #now the lines
        p_orig.line('x','y', line_width=2, color="red", source=old_source)
        p_sort.line('x','y', line_width=2, color="red", source=new_source)

        plots = {'original':p_orig, 'sorted':p_sort}
        return components(plots)


def distance(x1, y1, x2, y2):
    dist = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    return dist


# Distance callback

class CreateDistanceCallback(object):
    """Create callback to calculate distances between points."""

    def __init__(self, locations):
        """Initialize distance array."""
        size = len(locations)
        self.matrix = {}

        for from_node in range(size):
            self.matrix[from_node] = {}
            for to_node in range(size):
                if from_node == to_node:
                    self.matrix[from_node][to_node] = 0
                else:
                    x1 = locations[from_node][0]
                    y1 = locations[from_node][1]
                    x2 = locations[to_node][0]
                    y2 = locations[to_node][1]
                    self.matrix[from_node][to_node] = distance(x1, y1, x2, y2)

    def Distance(self, from_node, to_node):
        return int(self.matrix[from_node][to_node])
