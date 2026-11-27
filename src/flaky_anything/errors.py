"""Errors the user can act on. The CLI renders these without a traceback."""


class FlakyAnythingError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
