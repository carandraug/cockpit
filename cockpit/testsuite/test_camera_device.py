#!/usr/bin/env python3

## Copyright (C) 2023 David Miguel Susano Pinto <carandraug@gmail.com>
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

from cockpit.devices.camera import _config_to_transform


class ParseOfCameraTransform(unittest.TestCase):
    def test_default_on_empty_string(self):
        self.assertEqual(_config_to_transform(""), (False, False, False))

    def test_expected_simple(self):
        self.assertEqual(
            _config_to_transform("(lr=True, ud=True, rot=True)"),
            (True, True, True),
        )
        self.assertEqual(
            _config_to_transform("(lr=False, ud=True, rot=True)"),
            (False, True, True),
        )
        self.assertEqual(
            _config_to_transform("(lr=True, ud=False, rot=True)"),
            (True, False, True),
        )
        self.assertEqual(
            _config_to_transform("(lr=True, ud=True, rot=False)"),
            (True, True, False),
        )

    def test_optional_whitespace(self):
        self.assertEqual(
            _config_to_transform("(lr=True,ud=False,rot=True)"),
            (True, False, True),
        )


if __name__ == "__main__":
    unittest.main()
