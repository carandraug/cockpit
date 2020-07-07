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

import unittest

import cockpit.gui.mainPanels
import cockpit.testsuite.test_gui


# Here's 7 manual tests to check that all works:
#
#    Adding a new channels add a new item on the menu.
#    Adding an existing channel will prompt for confirmation to replace it.
#    Removing a channel removes its menu
#    Export creates a file with all channels and import on a new session imports them all back.
#    importing a file in a session with existing channels, merges the two.
#    importing a file with duplicated channels, warns about it and replaces it.
#    Importing a file with duplicated channels, will do nothing if after the warning it is cancelled.

if __name__ == '__main__':
    unittest.main()
