"""Canonical table of the 50 US states.

Names match both the bundled GeoJSON (``properties.name``) and the GLAM
``feature_name`` values. ``usps`` is the USDA NASS ``state_alpha``; ``fips`` is
the 2-digit state ANSI/FIPS code used to join county data.
"""

# (name, usps, fips)
_STATES = [
    ("Alabama", "AL", "01"),
    ("Alaska", "AK", "02"),
    ("Arizona", "AZ", "04"),
    ("Arkansas", "AR", "05"),
    ("California", "CA", "06"),
    ("Colorado", "CO", "08"),
    ("Connecticut", "CT", "09"),
    ("Delaware", "DE", "10"),
    ("Florida", "FL", "12"),
    ("Georgia", "GA", "13"),
    ("Hawaii", "HI", "15"),
    ("Idaho", "ID", "16"),
    ("Illinois", "IL", "17"),
    ("Indiana", "IN", "18"),
    ("Iowa", "IA", "19"),
    ("Kansas", "KS", "20"),
    ("Kentucky", "KY", "21"),
    ("Louisiana", "LA", "22"),
    ("Maine", "ME", "23"),
    ("Maryland", "MD", "24"),
    ("Massachusetts", "MA", "25"),
    ("Michigan", "MI", "26"),
    ("Minnesota", "MN", "27"),
    ("Mississippi", "MS", "28"),
    ("Missouri", "MO", "29"),
    ("Montana", "MT", "30"),
    ("Nebraska", "NE", "31"),
    ("Nevada", "NV", "32"),
    ("New Hampshire", "NH", "33"),
    ("New Jersey", "NJ", "34"),
    ("New Mexico", "NM", "35"),
    ("New York", "NY", "36"),
    ("North Carolina", "NC", "37"),
    ("North Dakota", "ND", "38"),
    ("Ohio", "OH", "39"),
    ("Oklahoma", "OK", "40"),
    ("Oregon", "OR", "41"),
    ("Pennsylvania", "PA", "42"),
    ("Rhode Island", "RI", "44"),
    ("South Carolina", "SC", "45"),
    ("South Dakota", "SD", "46"),
    ("Tennessee", "TN", "47"),
    ("Texas", "TX", "48"),
    ("Utah", "UT", "49"),
    ("Vermont", "VT", "50"),
    ("Virginia", "VA", "51"),
    ("Washington", "WA", "53"),
    ("West Virginia", "WV", "54"),
    ("Wisconsin", "WI", "55"),
    ("Wyoming", "WY", "56"),
]


class State:
    __slots__ = ("name", "usps", "fips")

    def __init__(self, name, usps, fips):
        self.name = name
        self.usps = usps
        self.fips = fips

    def __repr__(self):
        return f"State({self.usps})"


STATES = [State(n, u, f) for (n, u, f) in _STATES]
BY_USPS = {s.usps: s for s in STATES}
BY_NAME = {s.name: s for s in STATES}
BY_FIPS = {s.fips: s for s in STATES}


def resolve(selection):
    """Return the list of State objects for a config ``states`` selection.

    ``selection`` may be the string ``"all"`` or a list of USPS codes.
    """
    if selection in (None, "all", "ALL", "*"):
        return list(STATES)
    out = []
    for item in selection:
        code = str(item).strip().upper()
        if code in BY_USPS:
            out.append(BY_USPS[code])
    return out or list(STATES)
