class TTSNotReady(RuntimeError):
    """The chosen voice cannot be spoken until something is set up. The pipeline stops on it instead of making silent narration."""
