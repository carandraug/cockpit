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

import sys
import traceback

import pkg_resources
import wx

import cockpit.events


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


## XXX: Still unsure about this design.  There's a single event type
## for all cockpit.events which means we can't easily pass the data
## from those events.  But having a new wx event for each of them
## seems overkill and cause more duplication.
EVT_COCKPIT = wx.PyEventBinder(wx.NewEventType())

class CockpitEvent(wx.PyEvent):
    def __init__(self):
        super(CockpitEvent, self).__init__()
        self.SetEventType(EVT_COCKPIT.typeId)


class EvtEmitter(wx.EvtHandler):
    """Receives :mod:`cockpit.events` and emits a custom :class:`wx.Event`.

    GUI elements must beget instances of :class:`EvtEmitter` for each
    cockpit event they are interested in subscribing, and then bind
    whatever to :const:`EVT_COCKPIT` events.  Like so::

      abort_emitter = cockpit.gui.EvtEmitter(window, cockpit.events.USER_ABORT)
      abort_emitter.Bind(cockpit.gui.EVT_COCKPIT, window.OnUserAbort)

    This ensures that cockpit events are handled in a wx compatible
    manner.  We can't have the GUI elements subscribe directly to
    :mod:`cockpit.events` because:

    1. The function or method used for subscription needs to be called
    on the main thread since wx, like most GUI toolkits, is not thread
    safe.

    2. unsubscribing is tricky.  wx objects are rarely destroyed so we
    can't use the destructor.  Even :meth:`wx.Window.Destroy` is not
    always called.

    """
    def __init__(self, parent):
        assert isinstance(parent, wx.Window)
        super(EvtEmitter, self).__init__()

        ## Destroy() is not called when the parent is destroyed, see
        ## https://github.com/wxWidgets/Phoenix/issues/630 so we need
        ## to handle this ourselves.
        parent.Bind(wx.EVT_WINDOW_DESTROY, self._OnParentDestroy)

    def _OnParentDestroy(self, evt):
        self.Destroy()


class CockpitEvtEmitter(EvtEmitter):
    def __init__(self, parent, cockpit_event_type):
        super(CockpitEvtEmitter, self).__init__(parent)
        self._cockpit_event_type = cockpit_event_type
        cockpit.events.subscribe(self._cockpit_event_type,
                                 self._EmitCockpitEvent)

    def _EmitCockpitEvent(self, *args, **kwargs):
        self.AddPendingEvent(CockpitEvent())

    def _Unsubscribe(self):
        cockpit.events.unsubscribe(self._cockpit_event_type,
                                   self._EmitCockpitEvent)

    def Destroy(self):
        self._Unsubscribe()
        return super(CockpitEvtEmitter, self).Destroy()


def ExceptionBox(caption="", parent=None):
    """Show python exception in a modal dialog.

    Creates a modal dialog without any option other than dismising the
    exception information.  This is similar to :func:`wx.MessageBox`
    but with an extra widget to show the traceback.

    Args:
        parent (wx.Window): parent window.
        caption (str): the dialog title.

    This only works during the handling of an exception since one
    can't retrieve the traceback after the handling of an exception.

    Would be nice if this looked more like :class:`wx.MessageDialog`.
    However, wx has native implementations for ``wx.MessageDialog`` so
    we can't create them by just using a :class:`wx.Dialog`.

    We don't use :class:`wx.RichMessageDialog` because we want the
    traceback of the exception in a monospaced font.

    """
    current_exception = sys.exc_info()[1]
    if current_exception is None:
        raise RuntimeError('Not handling an exception when called')

    dialog = wx.Dialog(parent, title=caption, name="exception-dialog")
    message = wx.StaticText(dialog, label=str(current_exception))
    pane_ctrl = wx.CollapsiblePane(dialog, label="Details")
    pane = pane_ctrl.Pane
    details = wx.StaticText(pane, label=traceback.format_exc())

    ## 'w.Font.Family = f' does not work
    details_font = details.Font
    details_font.Family = wx.FONTFAMILY_TELETYPE
    details.Font = details_font

    sizer_flags = wx.SizerFlags().Expand().Border()
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(message, sizer_flags)

    pane.Sizer = wx.BoxSizer(wx.VERTICAL)
    pane.Sizer.Add(details, sizer_flags)

    sizer.Add(pane_ctrl, sizer_flags)
    sizer.Add(dialog.CreateSeparatedButtonSizer(wx.OK), sizer_flags)

    dialog.SetSizerAndFit(sizer)
    dialog.Centre()
    dialog.ShowModal()
