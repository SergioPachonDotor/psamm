PSAMM metabolic modeling tools
==============================

[![Build Status](https://travis-ci.org/zhanglab/psamm.svg)](https://travis-ci.org/zhanglab/psamm)
[![Documentation Status](https://readthedocs.org/projects/psamm/badge/?version=latest)](https://readthedocs.org/projects/psamm/?badge=latest)

Tools related to metabolic modeling, reconstruction, data parsing and
formatting, consistency checking, automatic gap filling, and model simulations.

See [NEWS](NEWS.md) for information on recent changes. The `master` branch
tracks the latest release while the `develop` branch is the latest version in
development. Please apply any pull requests to the `develop` branch when
creating the pull request.

Install
-------

Use `pip` to install (it is recommended to use a
[Virtualenv](https://virtualenv.pypa.io/)):

``` shell
$ pip install git+https://github.com/zhanglab/psamm.git
```

The `psamm-import` tool is developed in
[a separate repository](https://github.com/zhanglab/psamm-import). After
installing PSAMM the `psamm-import` tool can be installed using:

``` shell
$ pip install git+https://github.com/zhanglab/psamm-import.git
```

Documentation
-------------

The documentation for PSAMM is available at
[Read the Docs](https://psamm.readthedocs.org/).

Software license
----------------

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

See [LICENCE](LICENSE).
