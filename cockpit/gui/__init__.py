#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2018 David Miguel Susano Pinto <david.pinto@bioch.ox.ac.uk>
##
## This file is part of Cockpit.
##
## Cockpit is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## Cockpit is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Cockpit.  If not, see <http://www.gnu.org/licenses/>.

import pkg_resources

## The resource_name argument for resource_filename is not a
## filesystem filepath.  It is a /-separated filepath, even on
## windows, so do not use os.path.join.

FONT_PATH = pkg_resources.resource_filename(
    'cockpit',
    'resources/fonts/UniversalisADFStd-Regular.otf'
)

BITMAPS_PATH = pkg_resources.resource_filename(
    'cockpit',
    'resources/bitmaps/'
)


## TODO: still testing if this is good.

import wx.lib.newevent
import cockpit.events

CockpitEvent, EVT_COCKPIT = wx.lib.newevent.NewEvent()


class EventHandler(wx.Window):
    """Receives `cockpit.events` and converts to `wx.Event`s.

    Events from cockpit make use of a pub sub architecture, GUI
    elements subscribe an unsubscribe to events with a function.  If
    gets called when the event is published, and unsubscribe when they
    are no longer inter

    """
    def __init__(self, parent, cockpit_event):
        super(EventHandler, self).__init__(parent)
        self._cockpit_event = cockpit_event
        cockpit.events.subscribe(self._cockpit_event, self._PostCockpitEvent)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._OnDestroy)

    def _PostCockpitEvent(self, *args, **kwargs):
        self.AddPendingEvent(CockpitEvent(**kwargs))

    def _OnDestroy(self, event):
        ## This only exists because we need to handle the event when
        ## it comes from the parent.  Otherwise, we don't get
        ## destroyed https://github.com/wxWidgets/Phoenix/issues/630
        self.Destroy()

    def Destroy(self):
        cockpit.events.unsubscribe(self._cockpit_event, self._PostCockpitEvent)
