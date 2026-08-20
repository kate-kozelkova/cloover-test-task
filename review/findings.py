from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    """Ordered so max()/comparisons work directly."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Finding:
    source: str  # "scanner:secrets", "scanner:egress", "llm", ...
    category: str  # "secret", "egress", "dependency", "pii", "auth", "correctness"
    severity: Severity
    message: str
    file: str = ""
    line: int | None = None
    hard_block: bool = False  # True => can never be auto-merged regardless of severity

    def to_dict(self):
        return {
            "source": self.source,
            "category": self.category,
            "severity": self.severity.name,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "hard_block": self.hard_block,
        }


@dataclass
class ScanResult:
    findings: list = field(default_factory=list)
    errored: bool = False
    error_message: str = ""
