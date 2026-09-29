import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dashboard_renderer as renderer


class CatalogGrowthTests(unittest.TestCase):
    def test_new_older_paper_preserves_all_published_addresses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fragments = root / 'fragments'
            fragments.mkdir()
            papers = [dict(title='Recent', year=2026), dict(title='Older', year=1995)]
            old_ids = [renderer.normalize_record(p, 'test')['id'] for p in papers]
            image_map = root / 'images.json'
            image_map.write_text(json.dumps({'images': [dict(id=i, rank=n) for n, i in enumerate(old_ids, 1)]}))
            papers.append(dict(title='Park', year=2002))
            (fragments / 'test.json').write_text(json.dumps({'records': papers}))
            with patch.multiple(renderer, ROOT=root, FRAGMENT_DIR=fragments, IMAGE_MAP_PATH=image_map):
                result, _ = renderer.load_records()
            self.assertEqual([r['id'] for r in result[:2]], old_ids)
            self.assertEqual([r['detail_page'] for r in result], [f'detail/paper-{i:03}.html' for i in (1, 2, 3)])

    def test_enrichment_accepts_new_package_but_rejects_missing_and_duplicate_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = [renderer.normalize_record(dict(title=f'Paper {i}'), 'test') for i in (1, 2)]
            for i, record in enumerate(records, 1):
                record['rank'] = i
                package = dict(schema_version=3, record_count=1, records=[dict(
                    id=record['id'], rank=i, card_summary='s' * 120, one_line='summary',
                    sections={}, key_figure_labels={}, evidence_pages={})])
                (root / f'{i}.json').write_text(json.dumps(package))
            with patch.object(renderer, 'ENRICHED_DIR', root):
                self.assertEqual(len(renderer.merge_enriched(records)), 2)
                (root / 'copy.json').write_text((root / '1.json').read_text())
                with self.assertRaises(SystemExit):
                    renderer.merge_enriched(records)
                (root / 'copy.json').unlink()
                (root / '2.json').unlink()
                with self.assertRaises(SystemExit):
                    renderer.merge_enriched(records)


if __name__ == '__main__':
    unittest.main()
