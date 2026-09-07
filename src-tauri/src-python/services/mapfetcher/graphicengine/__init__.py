"""Graphics Engine Service, split by concern:

- base.py: __init__, font/image loading, shared constants (_GraphicsEngineBase)
- drawing.py: route line + waypoint pin drawing (_DrawingMixin)
- sprites.py: sprite blitting and cached walker/vehicle icon sprites (_SpriteMixin)
- icons.py: small vector mode icons for the summary card (_IconMixin)
- popup_box.py: cinematic pause overlay + popup/HUD card rendering (_PopupBoxMixin)
- fullscreen.py: fullscreen popup transition, B-roll playback, consolidated
  freeze/scale/hold/fade sequence (_FullscreenMixin)
- cards.py: end-of-video summary stat card + generic card compositing (_CardMixin)

`GraphicsEngine` composes all of the above, preserving the exact same method
set/behavior as the original single-file class.
"""

from .base import _GraphicsEngineBase
from .cards import _CardMixin
from .drawing import _DrawingMixin
from .fullscreen import _FullscreenMixin
from .icons import _IconMixin
from .popup_box import _PopupBoxMixin
from .sprites import _SpriteMixin


class GraphicsEngine(
    _DrawingMixin,
    _SpriteMixin,
    _IconMixin,
    _PopupBoxMixin,
    _FullscreenMixin,
    _CardMixin,
    _GraphicsEngineBase,
):
    pass


__all__ = ["GraphicsEngine"]
