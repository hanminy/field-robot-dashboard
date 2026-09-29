import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from publish import Exporter, FIELD, validate


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.vault = self.base / 'vault'
        (self.vault / FIELD).mkdir(parents=True)
        self.exporter = Exporter(self.vault, self.base / 'site')

    def tearDown(self):
        self.temp.cleanup()

    def test_private_note_and_pdf_are_not_published(self):
        private = self.vault / 'private.md'
        private.write_text('private')
        pdf = self.vault / FIELD / 'paper.pdf'
        pdf.write_bytes(b'private PDF')
        source = self.vault / FIELD / 'note.md'
        for path in (private, pdf):
            self.assertIsNone(self.exporter.link(str(path), source, Path('notes/a.html')))
        self.assertFalse(self.exporter.output.exists())

    def test_note_edits_are_rendered_and_hidden_comments_removed(self):
        source = self.vault / FIELD / 'paper_요약.md'
        target = Path('notes/a.html')
        self.exporter.notes[source] = target
        source.write_text('---\nprivate: hidden_property\n---\n# Before\n%%secret_comment%%')
        self.exporter.render_note(source, target)
        old = (self.exporter.output / target).read_text()
        self.assertIn('Before', old)
        self.assertNotIn('hidden_property', old)
        self.assertNotIn('secret_comment', old)
        source.write_text('# After\nChanged live summary')
        self.exporter.render_note(source, target)
        new = (self.exporter.output / target).read_text()
        self.assertIn('Changed live summary', new)
        self.assertNotIn('Before', new)

    def test_validator_rejects_escaping_and_missing_links(self):
        root = self.exporter.output
        root.mkdir()
        for link in ('../../private.md', 'missing.png'):
            (root / 'index.html').write_text(f'<img src="{link}">')
            with self.assertRaises(ValueError):
                validate(root)

    def test_ambiguous_wikilink_does_not_select_arbitrary_file(self):
        for folder in ('a', 'b'):
            path = self.vault / FIELD / folder
            path.mkdir()
            (path / 'same.png').write_bytes(b'dummy')
        exporter = Exporter(self.vault, self.base / 'site')
        self.assertIsNone(exporter.resolve('same.png', self.vault / FIELD / 'note.md'))


if __name__ == '__main__':
    unittest.main()
