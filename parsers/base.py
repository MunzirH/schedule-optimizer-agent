"""
Base parser interface.

Every file format parser must subclass BaseParser and implement parse().
The registry auto-discovers parsers and routes files to the right one.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from models.schedule import ScheduleData


class ParseError(Exception):
    """Raised when a parser cannot read or validate a file."""
    pass


class BaseParser(ABC):
    """
    Abstract base class for all schedule file parsers.

    Subclasses must implement:
      - supported_extensions: list of file extensions this parser handles
      - parse(file_path): read the file and return a ScheduleData object
      - can_parse(file_path): optional sniff test beyond extension matching
    """

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this parser handles (e.g. ['.xer', '.XER'])."""
        ...

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Human-readable name of the format (e.g. 'Primavera P6 XER')."""
        ...

    @abstractmethod
    def parse(self, file_path: str) -> ScheduleData:
        """
        Parse a schedule file and return a unified ScheduleData object.

        Raises ParseError if the file cannot be read or is invalid.
        """
        ...

    def can_parse(self, file_path: str) -> bool:
        """
        Optional deeper check beyond extension matching.

        Override this to sniff file headers (e.g. XER starts with 'ERMHDR').
        Default implementation checks extension only.
        """
        ext = Path(file_path).suffix.lower()
        return ext in [e.lower() for e in self.supported_extensions]
