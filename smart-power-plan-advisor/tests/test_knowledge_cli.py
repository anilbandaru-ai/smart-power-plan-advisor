import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.knowledge.cli import source_files, main
from backend.knowledge.config import Settings
from backend.knowledge.models import DocumentReviewRequired


class KnowledgeCliTests(unittest.TestCase):
    def test_cache_is_opt_in_and_regular_txu_pdfs_are_included(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ('_txu/cache.pdf', 'TXU/user.PDF', 'provider/plan.pdf'):
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.touch()
            settings = Settings(data_dir=root)
            self.assertEqual([p.relative_to(root).as_posix() for p in source_files(settings)],
                             ['TXU/user.PDF', 'provider/plan.pdf'])
            self.assertEqual(len(source_files(settings, True)), 3)

    def test_invalid_selected_document_never_connects_or_publishes(self):
        with patch('sys.argv', ['cli', 'ingest']), \
             patch('backend.knowledge.cli.source_files', return_value=[]), \
             patch('backend.knowledge.audit.audit_corpus', return_value={'files': [], 'failed': 0}), \
             patch('backend.knowledge.audit.write_audit'), \
             patch('backend.knowledge.documents.build_corpus', side_effect=DocumentReviewRequired('review required')), \
             patch('backend.knowledge.providers.Providers') as provider, \
             patch('backend.knowledge.ingest.publish') as publish:
            with self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 1)
            provider.assert_not_called()
            publish.assert_not_called()
