"""Versioned prompt files.

Each prompt lives in app/llm/prompts/<name>_v<version>.md and ships with the
package. A changed prompt gets a new file and a new version, so every stored
output can say exactly which prompt produced it.
"""

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def id(self) -> str:
        """The version recorded with outputs, such as "jd_parse_v1"."""
        return f"{self.name}_v{self.version}"


JD_PARSE = ("jd_parse", 1)
REWRITE = ("rewrite", 1)


@lru_cache
def load_prompt(name: str, version: int) -> Prompt:
    path = resources.files("app.llm").joinpath("prompts", f"{name}_v{version}.md")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Prompt {name}_v{version} is empty.")
    return Prompt(name=name, version=version, text=text)
