"""CSV ingestion: load, profile, preserve raw data immutably."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import DatasetProfile, ParseError

# ponytail: utf-8-sig (handles BOM) then latin-1 covers the vast majority of
# industrial CSVs without a chardet dependency. Add charset detection only if
# real files fail to decode.
_ENCODINGS = ("utf-8-sig", "latin-1")
_PREVIEW_ROWS = 5


def load_csv(path: str | Path) -> tuple[pd.DataFrame, DatasetProfile]:
    """Load a CSV into a fresh DataFrame plus a DatasetProfile.

    Delimiter is auto-sniffed. Encoding falls back utf-8-sig -> latin-1. The
    returned DataFrame is a copy; the caller may mutate it freely. Raises
    ParseError if the file is missing, empty, or unparseable.
    """
    path = Path(path)
    if not path.is_file():
        raise ParseError(f"file not found: {path}")

    last_error: Exception | None = None
    df: pd.DataFrame | None = None
    for encoding in _ENCODINGS:
        try:
            df = pd.read_csv(path, sep=None, engine="python", encoding=encoding)
        except UnicodeDecodeError as error:
            last_error = error
            continue
        except Exception as error:  # empty file, malformed structure, etc.
            raise ParseError(f"failed to parse {path.name}: {error}") from error
        break
    if df is None:
        raise ParseError(
            f"failed to decode {path.name} as any of {_ENCODINGS}: {last_error}"
        )

    return df.copy(), profile(df)


def profile(df: pd.DataFrame) -> DatasetProfile:
    columns = [str(c) for c in df.columns]
    return DatasetProfile(
        row_count=len(df),
        columns=tuple(columns),
        dtypes={c: str(df[c].dtype) for c in columns},
        null_counts={c: int(df[c].isna().sum()) for c in columns},
        head_preview=tuple(
            tuple("" if pd.isna(value) else str(value) for value in df.iloc[i])
            for i in range(min(_PREVIEW_ROWS, len(df)))
        ),
    )
