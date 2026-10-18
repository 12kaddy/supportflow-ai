"""Transparent word-error counts; no transliteration or translation of references."""

import re
import unicodedata


def words(text):
    text = unicodedata.normalize("NFC", text).casefold()
    text = "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)
    return re.findall(r"\S+", text)


def word_errors(reference, hypothesis):
    expected, actual = words(reference), words(hypothesis)
    if not expected:
        raise ValueError("A nonempty reference transcript is required")
    previous = list(range(len(actual) + 1))
    for row, word in enumerate(expected, 1):
        current = [row]
        for column, other in enumerate(actual, 1):
            current.append(
                min(previous[column] + 1, current[-1] + 1, previous[column - 1] + (word != other))
            )
        previous = current
    return {"errors": previous[-1], "reference_words": len(expected)}


def summarize(rows):
    results = {}
    for language in sorted({row["language"] for row in rows}):
        subset = [row for row in rows if row["language"] == language]
        completed = [row for row in subset if "errors" in row]
        total = sum(row["reference_words"] for row in completed)
        results[language] = {
            "total": len(subset),
            "completed": len(completed),
            "failed": len(subset) - len(completed),
            "wer": sum(row["errors"] for row in completed) / total if total else None,
            "mean_asr_latency_ms": sum(row["asr_latency_ms"] for row in completed) / len(completed)
            if completed
            else None,
        }
    return results
