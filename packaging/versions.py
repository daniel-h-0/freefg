#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Release names and their order: one reading for the installer's downgrade refusal and Setup's labels."""
import re

# product-major.minor[.patch[.build]], then an optional pre-release: -preview, -previewN or -preview.N, -rcN (rc alone: rc0).
NAME = re.compile(r'[a-z][a-z0-9-]*?-([0-9]+(?:\.[0-9]+){1,3})(?:-(preview|rc)(?:\.?([0-9]+))?)?')
# A pre-release comes before the release with the same numbers: the previews, then the release candidates.
STAGES = {'preview': 0, 'rc': 1, None: 2}


def release_number(name):
    """A release name's version as a tuple that sorts as the releases do (freefg-1.2.0-preview < freefg-1.2.0-preview.2 <
    freefg-1.2.0-rc1 < freefg-1.2.0 < freefg-1.2.0.1), or None for any other name (a tester build's, an unknown suffix):
    unknown, which a caller comparing two releases must not read as older or newer."""
    found = NAME.fullmatch(str(name or ''))
    if not found:
        return None
    numbers = tuple(int(part) for part in found[1].split('.'))
    return numbers + (0,) * (4 - len(numbers)) + (STAGES[found[2]], int(found[3] or 0))
