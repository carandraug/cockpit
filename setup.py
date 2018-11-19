#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2018 David Miguel Susano Pinto <david.pinto@bioch.ox.ac.uk>
##
## Copying and distribution of this file, with or without modification,
## are permitted in any medium without royalty provided the copyright
## notice and this notice are preserved.  This file is offered as-is,
## without any warranty.

import os.path
import sys

import setuptools
import setuptools.command.sdist

extra_requires = []
if sys.version_info < (3,2):
    extra_requires += ['futures'] # for concurrent.futures
if sys.version_info < (3,4):
    extra_requires += ['enum34']

## Modify the sdist command class to include extra files in the source
## distribution.  We could also have a MANIFEST file but we'd rather
## not have the distribution configuration over multiple files.
manifest_files = [
    'README.md',
    'COPYING',
    os.path.join('cockpit', 'resources', 'fonts', 'Universalis_COPYING.txt'),
    os.path.join('cockpit', 'resources', 'fonts', 'Universalis_NOTICE.txt'),
]
class sdist(setuptools.command.sdist.sdist):
    def make_distribution(self):
        self.filelist.extend(manifest_files)
        super(sdist, self).make_distribution()


setuptools.setup(
    name = 'cockpit',
    version = '2.9.0+dev',
    description = 'Hardware agnostic microscope user interface',
    long_description = open('README.md', 'r').read(),
    license = 'GPL-3.0+',

    url = "https://github.com/MicronOxford/cockpit",

    author = '',
    author_email = '',

    ## https://pypi.org/pypi?:action=list_classifiers
    classifiers = [
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
    ],

    packages = setuptools.find_packages(),
    package_data = {
        'cockpit' : [
            os.path.join('resources', 'bitmaps', '*.png'),
            os.path.join('resources', 'bitmaps', '*.ico'),
            os.path.join('resources', 'fonts', '*.otf'),
        ],
    },

    install_requires = [
        'matplotlib',
        'numpy',
        'scipy',
        'wxPython',
        'Pyro4',
        'Pyllow', # temporary until wxPython 4.0.4 release (issue #319)
        'pyserial',
        'PyOpenGL',
        'six',
    ] + extra_requires,

    test_suite = 'cockpit.testsuite',

    entry_points = {
        'gui_scripts': [
            'cockpit = cockpit:main',
        ]
    },

    cmdclass = {
        'sdist' : sdist,
    },
)
