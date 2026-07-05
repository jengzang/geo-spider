from __future__ import annotations

from datetime import UTC, datetime

from dmfw_places_spider.exporters.manager import ExportManager
from dmfw_places_spider.geo.mock import MockGeoCoder
from dmfw_places_spider.models.region import CrawlRunRecord, PipelineResult
from dmfw_places_spider.sources.mock import MockAdministrativeSource
from dmfw_places_spider.storage.sqlite import SQLiteRegionRepository


class SamplePipeline:
    def __init__(self, repository: SQLiteRegionRepository, export_manager: ExportManager) -> None:
        self.repository = repository
        self.export_manager = export_manager
        self.source = MockAdministrativeSource()
        self.geocoder = MockGeoCoder()

    def run(self, export_dir, export_formats: list[str]) -> PipelineResult:
        started_at = datetime.now(UTC).isoformat()
        run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        regions = self.source.fetch_regions()
        enriched_regions = self.geocoder.enrich(regions)

        self.repository.initialize()
        self.repository.upsert_regions(enriched_regions)
        exported = self.export_manager.export(enriched_regions, export_dir, export_formats)

        finished_at = datetime.now(UTC).isoformat()
        self.repository.record_crawl_run(
            CrawlRunRecord(
                run_id=run_id,
                source_name=self.source.name,
                status="success",
                item_count=len(enriched_regions),
                started_at=started_at,
                finished_at=finished_at,
            )
        )
        return PipelineResult(
            run_id=run_id,
            region_count=len(enriched_regions),
            source_name=self.source.name,
            exported_files=exported,
        )
