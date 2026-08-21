"""Registry of known datasets and their profiles."""

from __future__ import annotations

import json
from pathlib import Path

from dimer.data_context.schema_profile import DatasetProfile, load_profile, profile_dataset, save_profile
from dimer.storage.artifacts import get_dimer_dir


class DatasetRegistry:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace
        self._registry_path = get_dimer_dir(workspace) / "dataset_registry.json"
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._registry_path.exists():
            self._data = json.loads(self._registry_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def register(self, path: str | Path, profile: DatasetProfile | None = None) -> DatasetProfile:
        p = Path(path).resolve()
        key = str(p)
        if profile is None:
            profile = profile_dataset(p)
        out = save_profile(profile, self.workspace)
        self._data[key] = str(out)
        self._save()
        return profile

    def get(self, path: str | Path) -> DatasetProfile | None:
        key = str(Path(path).resolve())
        profile_path = self._data.get(key)
        if profile_path:
            return DatasetProfile.model_validate_json(Path(profile_path).read_text(encoding="utf-8"))
        return load_profile(path, self.workspace)

    def list_datasets(self) -> list[str]:
        return list(self._data.keys())
