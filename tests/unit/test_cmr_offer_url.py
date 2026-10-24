"""Offer URL selection for CMR teardown.

``juju offer`` takes ``<model>.<app>:<endpoint>``. ``remove-offer`` takes the
offer URL. These tests lock that distinction without a controller.
"""

from tests.integration.test_cmr import _offer_for_app, _offer_target

_APP = "juju-norma-k8s"
_MODEL = "jubilant-fa27a094"


def test_offer_url_field_is_used_as_is():
    offers = {
        _APP: {
            "application": _APP,
            "offer-url": f"admin/{_MODEL}.{_APP}",
            "endpoints": {"calibration-provider": {"interface": "calibration"}},
        }
    }
    name, info = _offer_for_app(offers, _APP)
    target = _offer_target(name, info, _MODEL)
    assert target == f"admin/{_MODEL}.{_APP}"
    assert ":" not in target


def test_bare_offer_name_becomes_model_dot_offer():
    offers = {
        _APP: {
            "application": _APP,
            "endpoints": {"calibration-provider": {}},
        }
    }
    name, info = _offer_for_app(offers, _APP)
    assert _offer_target(name, info, _MODEL) == f"{_MODEL}.{_APP}"


def test_qualified_key_without_offer_url_is_kept():
    key = f"admin/{_MODEL}.{_APP}"
    offers = {key: {"application": _APP, "endpoints": {"calibration-provider": {}}}}
    name, info = _offer_for_app(offers, _APP)
    assert _offer_target(name, info, _MODEL) == key


def test_endpoint_form_is_not_an_offer_url():
    """The string passed to ``juju offer`` is not what ``remove-offer`` accepts."""
    offers = {
        _APP: {
            "application": _APP,
            "offer-url": f"admin/{_MODEL}.{_APP}",
            "endpoints": {"calibration-provider": {}},
        }
    }
    name, info = _offer_for_app(offers, _APP)
    target = _offer_target(name, info, _MODEL)
    assert target != f"{_MODEL}.{_APP}:calibration-provider"


def test_match_is_by_application_not_a_sibling_offer():
    offers = {
        "norma-cmr-offerer": {
            "application": "norma-cmr-offerer",
            "offer-url": f"admin/{_MODEL}.norma-cmr-offerer",
            "endpoints": {"calibration-provider": {}},
        },
        _APP: {
            "application": _APP,
            "offer-url": f"{_MODEL}.{_APP}",
            "endpoints": {"calibration-provider": {}},
        },
    }
    name, info = _offer_for_app(offers, "norma-cmr-offerer")
    assert _offer_target(name, info, _MODEL) == f"admin/{_MODEL}.norma-cmr-offerer"
