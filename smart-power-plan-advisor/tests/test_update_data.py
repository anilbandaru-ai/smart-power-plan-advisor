"""Portable updater tests; provider work is mocked and all outputs are temporary."""
import argparse
from contextlib import ExitStack, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend import update_data as updater
from backend.knowledge.config import Settings
from backend.knowledge.models import DocumentReviewRequired


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='advisor update ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / 'data'; self.data.mkdir()
        self.pdf = self.data / 'plan.pdf'; self.pdf.write_bytes(b'%PDF-fixture')
        self.settings = Settings(openai_key='never-print-openai', pinecone_key='never-print-pinecone',
                                 data_dir=self.data, manifest_path=self.root / 'output' / 'knowledge.json')
        self.config = updater.Configuration(self.settings, self.root / 'output' / 'plans.sqlite3', [])
        self.manifest = {'namespace': 'power-plans-fixture', 'documents': [
            {'filename': 'plan.pdf', 'sha256': sha256(self.pdf.read_bytes()).hexdigest()}], 'chunks': 1}
        self.events = []
        self.extractor = Mock()
        self.providers = Mock()
        self.providers.connect.side_effect = lambda: self.events.append('connect')
        stack = ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(patch.object(updater, 'configuration', return_value=self.config))
        stack.enter_context(patch('backend.catalog.extract.Extractor', return_value=self.extractor))
        self.sync = stack.enter_context(patch('backend.catalog.sync.sync', side_effect=self.catalog_sync))
        self.txu = stack.enter_context(patch('backend.catalog.txu.sync_txu', side_effect=self.txu_sync))
        self.audit = stack.enter_context(patch('backend.knowledge.audit.audit_corpus', return_value={'files': [], 'failed': 0}))
        self.build = stack.enter_context(patch('backend.knowledge.documents.build_corpus', side_effect=self.prepare))
        self.factory = stack.enter_context(patch('backend.knowledge.providers.Providers', return_value=self.providers))
        # Exercise the real atomic-manifest publisher, with only its upsert mocked.
        self.providers.upsert.side_effect = lambda records, namespace: self.events.append('upsert')

    def prepare(self, settings, paths):
        self.events.append('prepare')
        return self.manifest, [{'id': 'chunk'}]

    def catalog_sync(self, store, root, extractor, **options):
        self.events.append('sqlite')
        store.initialize()
        store.source('plan.pdf', 'hash', None, 'ready', None, '2026-09-12')
        return {'files': 1, 'extracted': 1, 'reused': 0, 'failed': 0, 'removed': 0}

    def txu_sync(self, store, root, zips, **kwargs):
        self.events.append('txu')
        return {'zips': len(zips), 'failed': 0, 'offers': 43, 'blocked': 43}

    def run_command(self, *args):
        output = io.StringIO()
        with redirect_stdout(output): code = updater.main(list(args))
        self.assertNotIn('never-print', output.getvalue())
        return code, json.loads(output.getvalue())

    def test_check_does_not_extract_call_providers_or_create_outputs(self):
        code, report = self.run_command('--check')
        self.assertEqual(code, 0); self.assertEqual(report['status'], 'check_passed')
        self.assertEqual(report['pdf_files'], 1)
        self.assertFalse((self.root / 'output').exists())
        self.build.assert_not_called(); self.sync.assert_not_called(); self.factory.assert_not_called()

    def test_failed_audit_prevents_catalog_and_provider_work(self):
        self.audit.return_value = {'files': [{'filename': 'plan.pdf', 'status': 'failed'}], 'failed': 1}
        code, report = self.run_command()
        self.assertEqual(code, 1)
        self.assertIn('audit', report['error'])
        self.build.assert_not_called()
        self.sync.assert_not_called()
        self.factory.assert_not_called()
        self.assertTrue((self.settings.manifest_path.parent / 'rag-audit.json').exists())

    def test_updates_sqlite_then_rag_and_closes_resources(self):
        code, report = self.run_command()
        self.assertEqual(code, 0)
        self.assertEqual(self.events, ['prepare', 'sqlite', 'connect', 'upsert'])
        self.assertEqual(report['sqlite']['status'], 'updated')
        self.assertEqual(report['rag']['status'], 'updated')
        self.assertEqual(json.loads(self.settings.manifest_path.read_text()), self.manifest)
        self.assertTrue(self.config.db.is_file())
        self.extractor.close.assert_called_once(); self.providers.close.assert_called_once()
        self.assertTrue(self.sync.call_args.kwargs['retry'])

    def test_unchanged_rag_skips_provider_but_force_republishes(self):
        self.settings.manifest_path.parent.mkdir()
        self.settings.manifest_path.write_text(json.dumps(self.manifest))
        code, report = self.run_command()
        self.assertEqual(code, 0); self.assertEqual(report['rag']['status'], 'unchanged')
        self.assertFalse(report['rag']['remote_state_checked']); self.factory.assert_not_called()
        self.config.force = True; self.config.refresh_tdu = True
        code, report = self.run_command('--force', '--refresh-tdu')
        self.assertEqual(code, 0); self.assertEqual(report['rag']['status'], 'updated')
        self.assertTrue(self.sync.call_args.kwargs['force'])
        self.assertTrue(self.sync.call_args.kwargs['refresh_tdu'])

    def test_txu_blocks_are_not_listing_failures_and_rag_scope_is_explicit(self):
        managed = self.data / '_txu'; managed.mkdir(); (managed / 'download.PDF').write_bytes(b'provider')
        self.config.zips = ['78681']
        code, report = self.run_command('--zip', '78681')
        self.assertEqual(code, 0); self.assertEqual(report['txu']['blocked'], 43)
        self.assertEqual(self.events[:3], ['txu', 'prepare', 'sqlite'])
        self.assertEqual(self.build.call_args.kwargs['paths'], [self.pdf])
        self.config.include_txu_rag = True
        code, report = self.run_command('--include-txu-rag')
        self.assertEqual(code, 0)
        self.assertTrue(self.txu.call_args.kwargs['download_efls'])
        self.assertIn(managed / 'download.PDF', self.build.call_args.kwargs['paths'])

    def test_preparation_failure_preserves_manifest_and_does_not_sync_sqlite(self):
        self.settings.manifest_path.parent.mkdir()
        self.settings.manifest_path.write_text('previous manifest')
        self.build.side_effect = DocumentReviewRequired('plan.pdf, page 2: review required')
        code, report = self.run_command()
        self.assertEqual(code, 1); self.assertEqual(report['stage'], 'prepare_rag')
        self.assertIn('page 2', report['error'])
        self.assertEqual(self.settings.manifest_path.read_text(), 'previous manifest')
        self.sync.assert_not_called(); self.factory.assert_not_called()

    def test_catalog_partial_failure_stops_rag(self):
        self.sync.return_value = {'failed': 1}
        self.sync.side_effect = None
        code, report = self.run_command()
        self.assertEqual(code, 1); self.assertEqual(report['sqlite']['status'], 'partial')
        self.assertEqual(report['rag']['status'], 'prepared')
        self.factory.assert_not_called(); self.extractor.close.assert_called_once()

    def test_upsert_failure_retains_old_manifest_and_completed_sqlite(self):
        self.settings.manifest_path.parent.mkdir()
        self.settings.manifest_path.write_text('old manifest')
        self.providers.upsert.side_effect = RuntimeError('never-print-provider-body')
        code, report = self.run_command()
        self.assertEqual(code, 1); self.assertEqual(report['stage'], 'rag')
        self.assertEqual(report['sqlite']['status'], 'updated')
        self.assertEqual(report['rag']['status'], 'failed')
        self.assertTrue(self.config.db.is_file())
        self.assertEqual(self.settings.manifest_path.read_text(), 'old manifest')
        self.providers.close.assert_called_once()

    def test_changed_pdf_blocks_publication_and_failed_txu_stops_next_stages(self):
        def changed(*args, **kwargs):
            self.pdf.write_bytes(b'changed')
            return {'failed': 0}
        self.sync.side_effect = changed
        code, report = self.run_command()
        self.assertEqual(code, 1); self.assertIn('changed', report['error'])
        self.factory.assert_not_called()
        self.config.zips = ['78681']
        self.txu.side_effect = None; self.txu.return_value = {'failed': 1}
        self.build.reset_mock()
        code, report = self.run_command('--zip', '78681')
        self.assertEqual(code, 1); self.assertEqual(report['txu']['status'], 'partial')
        self.build.assert_not_called()

    def test_source_changed_during_upsert_cannot_activate_manifest(self):
        self.settings.manifest_path.parent.mkdir()
        self.settings.manifest_path.write_text('previous manifest')
        self.providers.upsert.side_effect = lambda *args: self.pdf.write_bytes(b'changed during embedding')
        code, report = self.run_command()
        self.assertEqual(code, 1); self.assertEqual(report['rag']['status'], 'failed')
        self.assertEqual(self.settings.manifest_path.read_text(), 'previous manifest')
        self.providers.close.assert_called_once()


class ConfigurationTests(unittest.TestCase):
    def args(self, **values):
        return argparse.Namespace(env_file=None, data_dir=None, db=None, manifest=None,
            zips=[], include_txu_rag=False, force=False, refresh_tdu=False, **values)

    def test_paths_env_precedence_and_preflight_no_mutation(self):
        with tempfile.TemporaryDirectory(prefix='paths with spaces ') as directory:
            root = Path(directory).resolve(); (root / 'data').mkdir()
            (root / '.env').write_text('OPENAI_API_KEY=file-only\nPINECONE_API_KEY=file-only\n')
            with patch.object(updater, 'ROOT', root), patch.dict(os.environ, {'OPENAI_API_KEY': 'environment-wins'}, clear=True):
                config = updater.configuration(self.args())
                self.assertEqual(config.settings.openai_key, 'environment-wins')
                self.assertEqual(config.settings.data_dir, root / 'data')
                self.assertEqual(config.db, root / '.data' / 'plans.sqlite3')
                self.assertEqual(config.settings.manifest_path, root / '.data' / 'knowledge.json')
                self.assertFalse((root / '.data').exists())
                same = self.args(); same.db = '.data/same'; same.manifest = '.data/same'
                with self.assertRaises(updater.UpdateError): updater.configuration(same)
                invalid = self.args(); invalid.zips = ['1234x']
                with self.assertRaisesRegex(updater.UpdateError, 'five digits'): updater.configuration(invalid)

    def test_missing_dependencies_and_credentials_have_safe_actionable_errors(self):
        with patch('importlib.util.find_spec', return_value=None):
            with self.assertRaisesRegex(updater.UpdateError, 'requirements-rag.txt'):
                updater.configuration(self.args())
        with tempfile.TemporaryDirectory() as directory, patch.object(updater, 'ROOT', Path(directory)), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(updater.UpdateError, 'OPENAI_API_KEY'):
                updater.configuration(self.args())

    def test_rag_settings_honor_shared_data_root(self):
        with patch.dict(os.environ, {'PLAN_DATA_DIR': '/custom/documents'}):
            self.assertEqual(Settings.from_env().data_dir, Path('/custom/documents'))

    def test_uppercase_discovery_and_source_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = root / 'data'; data.mkdir()
            (data / 'PLAN.PDF').write_bytes(b'pdf')
            config = updater.Configuration(Settings(data_dir=data), root / 'db', [])
            self.assertEqual([p.name for p in updater.source_files(config)], ['PLAN.PDF'])
            outside = root / 'outside.pdf'; outside.write_bytes(b'outside')
            try: (data / 'escape.pdf').symlink_to(outside)
            except OSError: return  # Windows may not grant symlink creation.
            with self.assertRaises(updater.UpdateError): updater.source_files(config)


class CorpusSelectionTests(unittest.TestCase):
    def test_explicit_sources_preserve_uppercase_citations_and_exclude_bad_downloads(self):
        from backend.knowledge.documents import build_corpus, source_path
        source = Path(__file__).resolve().parents[1] / 'data/choosetexaspower/EFL-6.pdf'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pdf = root / 'SOURCE.PDF'; pdf.write_bytes(source.read_bytes())
            (root / '_txu').mkdir(); (root / '_txu/bad.pdf').write_bytes(b'not PDF')
            settings = Settings(data_dir=root, manifest_path=root / 'manifest.json')
            manifest, records = build_corpus(settings, paths=[pdf, pdf])
            self.assertEqual(len(manifest['documents']), 1)
            self.assertEqual(manifest['documents'][0]['filename'], 'SOURCE.PDF')
            self.assertTrue(records)
            settings.manifest_path.write_text(json.dumps(manifest))
            self.assertEqual(source_path(settings, manifest['documents'][0]['id']), pdf)
            with self.assertRaises(ValueError): build_corpus(settings, paths=[root / '../outside.pdf'])
