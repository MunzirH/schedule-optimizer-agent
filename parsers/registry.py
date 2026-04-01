"""
Parser registry.

Routes files to the correct parser based on extension and content sniffing.
"""

from pathlib import Path

from parsers.base import BaseParser, ParseError
from models.schedule import ScheduleData


class ParserRegistry:
    """
    Central registry for all schedule file parsers.

    Usage:
        registry = ParserRegistry()
        registry.register(CSVScheduleParser())
        registry.register(XERParser())
        registry.register(XMLParser())

        schedule = registry.parse("path/to/file.xer")
    """

    def __init__(self):
        self._parsers: list[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        """Register a parser instance."""
        self._parsers.append(parser)

    def get_parser(self, file_path: str) -> BaseParser:
        """
        Find the appropriate parser for a file.

        First tries extension matching, then falls back to content sniffing.
        Raises ParseError if no parser can handle the file.
        """
        ext = Path(file_path).suffix.lower()

        # First pass: extension match
        for parser in self._parsers:
            if ext in [e.lower() for e in parser.supported_extensions]:
                return parser

        # Second pass: content sniffing (for files with wrong/missing extensions)
        for parser in self._parsers:
            try:
                if parser.can_parse(file_path):
                    return parser
            except Exception:
                continue

        supported = []
        for p in self._parsers:
            supported.extend(p.supported_extensions)

        raise ParseError(
            f"No parser found for '{Path(file_path).name}'. "
            f"Supported formats: {', '.join(sorted(set(supported)))}"
        )

    def parse(self, file_path: str) -> ScheduleData:
        """Parse a file using the appropriate parser."""
        parser = self.get_parser(file_path)
        return parser.parse(file_path)

    @property
    def supported_formats(self) -> dict[str, list[str]]:
        """Map of format name → supported extensions."""
        return {
            p.format_name: p.supported_extensions
            for p in self._parsers
        }


def create_default_registry() -> ParserRegistry:
    """
    Create a registry with all built-in parsers registered.

    This is the main entry point for the application.
    """
    from parsers.csv_parser import CSVScheduleParser
    from parsers.xer_parser import XERParser
    from parsers.xml_parser import XMLParser

    registry = ParserRegistry()
    registry.register(CSVScheduleParser())
    registry.register(XERParser())
    registry.register(XMLParser())
    return registry
