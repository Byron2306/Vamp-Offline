class Alignment:
    def __init__(self, wrap_text: bool | None = None, vertical: str | None = None):
        self.wrap_text = wrap_text
        self.vertical = vertical


class Font:
    def __init__(self, bold: bool | None = None):
        self.bold = bold

