#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2021 Centre National de la Recherche Scientifique (CNRS)
## Copyright (C) 2021 University of Oxford
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

## Copyright 2013, The Regents of University of California
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions
## are met:
##
## 1. Redistributions of source code must retain the above copyright
##   notice, this list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright
##   notice, this list of conditions and the following disclaimer in
##   the documentation and/or other materials provided with the
##   distribution.
##
## 3. Neither the name of the copyright holder nor the names of its
##   contributors may be used to endorse or promote products derived
##   from this software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
## "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
## LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
## FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
## COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
## INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
## BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
## LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
## CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
## ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.


## This module provides a dummy camera that generates test pattern images.

import ast
import re
import warnings

from cockpit.devices import device

def _config_to_transform(tstr):
    """Desribes a simple transform: (flip LR, flip UD, rotate 90)"""
    if not tstr:
        # Default is no transformation
        return (False, False, False)

    # We could write a regex that allows for more optional whitespace
    # and even change the order of the three values but we don't want
    # to make the regex more complicated than this to support that.
    pattern = "\(lr=(True|False),\s*ud=(True|False),\s*rot=(True|False)\)"

    match = re.fullmatch(pattern, tstr)
    if match:
        return (
            ast.literal_eval(match[1]),
            ast.literal_eval(match[2]),
            ast.literal_eval(match[3]),
        )
    else:
        # If there was no match it may be the old format of (int, int,
        # int) or an incorrectly formatted transform string.
        try:
            transform = tuple(
                [bool(int(t)) for t in tstr.strip('()').split(',')]
            )
        except:
            raise ValueError("invalid transform specification '%s'" % tstr)

        # We warn with "UserWarning" instead of "DeprecationWarning"
        # because the warning is about issues on the config file and
        # meant to the user and not to other developers.
        warnings.warn(
            "Specifying camera transform in the format"
            " '([1|0], [1|0], [1|0])' is deprecated.  Use the format"
            " '(lr=[True|False], ud=[True|False], rot=[True|False])'"
            " in the future.",
            UserWarning,
        )
        return transform

## CameraDevice subclasses Device with some additions appropriate
# to any camera.
class CameraDevice(device.Device):
    def __init__(self, name, config):
        super().__init__(name, config)
        # baseTransform depends on camera orientation and is constant.
        if 'transform' in config:
            self.baseTransform = _config_to_transform(config.get('transform'))
        else:
            self.baseTransform = None

    def updateTransform(self, pathTransform):
        """Apply a new pathTransform"""
        # pathTransform may change with changes in imaging path
        base = self.baseTransform
        # Flips cancel each other out. Rotations combine to flip both axes.
        lr = base[0] ^ pathTransform[0]
        ud = base[1] ^ pathTransform[1]
        rot = base[2] ^ pathTransform[2]
        if pathTransform[2] and base[2]:
            lr = not lr
            ud = not ud
        self._setTransform((lr, ud, rot))

    def _setTransform(self, transform):
        # Subclasses should override this if transforms are done on the device.
        self._transform = transform

    def finalizeInitialization(self):
        # Set fixed filter if defined in config
        if self.handler.wavelength is None and self.handler.dye is None:
            dye = self.config.get('dye', None)
            wavelength = self.config.get('wavelength', None)
            self.handler.updateFilter(dye, wavelength)
