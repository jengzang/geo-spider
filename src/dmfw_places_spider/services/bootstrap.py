from __future__ import annotations

from pathlib import Path

from dmfw_places_spider.config.settings import Settings
from dmfw_places_spider.exporters.manager import ExportManager
from dmfw_places_spider.models.region import PipelineResult
from dmfw_places_spider.pipelines.sample import SamplePipeline
from dmfw_places_spider.services.dmfw import run_dmfw_chars_pipeline
from dmfw_places_spider.storage.sqlite import SQLiteRegionRepository


def ensure_runtime_directories(settings: Settings) -> None:
    for path in (
        settings.raw_dir,
        settings.interim_dir,
        settings.processed_dir,
        settings.export_dir,
        settings.sqlite_path.parent,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)


def run_sample_pipeline(
    *,
    settings: Settings,
    source_name: str = "mock",
    export_formats: list[str] | None = None,
) -> PipelineResult:
    if source_name != "mock":
        raise ValueError(f"unsupported source: {source_name}")
    ensure_runtime_directories(settings)
    repository = SQLiteRegionRepository(settings.sqlite_path)
    export_manager = ExportManager()
    pipeline = SamplePipeline(repository=repository, export_manager=export_manager)
    return pipeline.run(settings.export_dir, export_formats or ["all"])


def export_from_database(settings: Settings, export_formats: list[str] | None = None) -> dict[str, str]:
    ensure_runtime_directories(settings)
    repository = SQLiteRegionRepository(settings.sqlite_path)
    repository.initialize()
    regions = repository.list_regions()
    export_manager = ExportManager()
    return export_manager.export(regions, settings.export_dir, export_formats or ["all"])
