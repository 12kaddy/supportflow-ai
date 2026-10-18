"""Load the approved corpus and produce deterministic, versioned chunks."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data/knowledge_base"


@dataclass(frozen=True)
class PolicyChunk:
    id: str
    text: str
    source: str
    version: str
    document_hash: str

    @property
    def citation(self):
        return f"{self.source}@{self.version}#{self.id}"


def split_text(text, size=900):
    text = text.strip()
    while text:
        end = min(size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", 0, end)
            if boundary > size // 2:
                end = boundary
        yield text[:end].strip()
        text = text[end:].strip()


def load_chunks(root=DEFAULT_ROOT):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Policy manifest must map source filenames to versions")
    if set(manifest) != {path.name for path in root.glob("*.md")}:
        raise ValueError("Every policy markdown file must be listed in the manifest")
    chunks = []
    for source, version in sorted(manifest.items()):
        if (
            Path(source).name != source
            or not source.endswith(".md")
            or not isinstance(version, str)
            or not version.strip()
        ):
            raise ValueError("Invalid policy manifest entry")
        text = (root / source).read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Empty policy: {source}")
        digest = hashlib.sha256(text.encode()).hexdigest()
        for index, passage in enumerate(split_text(text)):
            identifier = hashlib.sha256(
                f"{source}:{version}:{digest}:{index}".encode()
            ).hexdigest()[:24]
            chunks.append(PolicyChunk(identifier, passage, source, version, digest))
    return chunks
