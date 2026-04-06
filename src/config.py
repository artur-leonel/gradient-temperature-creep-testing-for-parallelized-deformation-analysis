from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    project_root: Path

    @property
    def src_dir(self) -> Path:
        return self.project_root / "src"

    @property
    def docs_dir(self) -> Path:
        return self.project_root / "docs"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def data_raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def data_raw_dic_mat_dir(self) -> Path:
        return self.data_raw_dir / "dic_mat"

    @property
    def data_raw_workbook_dir(self) -> Path:
        return self.data_raw_dir / "workbook"


def discover_project_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "src" / "pipeline" / "workflow.py").exists():
            return parent
    raise FileNotFoundError("Could not locate project root containing src/pipeline/workflow.py")


def get_paths(start: Path | None = None) -> Paths:
    return Paths(project_root=discover_project_root(start))


def ensure_directories(paths: Paths) -> None:
    required = [
        paths.docs_dir,
        paths.data_raw_dir,
        paths.data_raw_dic_mat_dir,
        paths.data_raw_workbook_dir,
    ]
    for directory in required:
        directory.mkdir(parents=True, exist_ok=True)
