"""The walk/map overview passes every stop-by — connected to the route or
not — instead of stopping at the connected ones: each pops its own card up
where it sits (_is_loose_stopby) and none of them hosts or joins a batch."""

from services.vdoprocessing.spatial_renderer.popups import _PopupMixin


def _popup(index, **data):
    return {"index": index, "data": data}


def test_a_connected_stopby_pops_up_on_its_own_like_any_other():
    stop = _popup(0)
    linked = _popup(1, is_stopby=True, connect_to_route=True, popup_image="p.jpg")
    loose = _popup(2, is_stopby=True, popup_image="p.jpg")
    nxt = _popup(3)
    _PopupMixin._attach_stopby_groups([stop, linked, loose, nxt], pass_by=True)

    for ap in (linked, loose):
        assert ap.get("stopby_host") is None
        assert not ap.get("stopby_group")
        assert _PopupMixin._is_loose_stopby(ap)


def test_the_course_style_still_batches_them():
    stop = _popup(0)
    linked = _popup(1, is_stopby=True, connect_to_route=True, popup_image="p.jpg")
    _PopupMixin._attach_stopby_groups([stop, linked], pass_by=False)
    assert linked.get("stopby_group") == []  # it hosts the run, as the course overview expects
