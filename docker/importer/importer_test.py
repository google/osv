# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Importer tests."""
import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

from google.cloud import ndb
import pygit2

import importer
import osv
from osv import tests

TEST_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'testdata')


class ImporterTest(unittest.TestCase):
  """Importer tests."""

  def _load_test_data(self, name):
    """Load test data."""
    with open(os.path.join(TEST_DATA_DIR, name)) as f:
      return f.read()

  def setUp(self):
    self.maxDiff = None  # pylint: disable=invalid-name
    self.tmp_dir = tempfile.mkdtemp()

    tests.mock_datetime(self)
    self.mock_repo = tests.mock_repository(self)
    self.mock_repo.add_file('2021-111.yaml', '')
    self.mock_repo.commit('User', 'user@email')

    self.remote_source_repo_path = self.mock_repo.path
    osv.SourceRepository(
        id='oss-fuzz',
        name='oss-fuzz',
        repo_url='file://' + self.remote_source_repo_path,
        repo_username='').put()

    osv.Bug(
        id='2017-134',
        affected=['FILE5_29', 'FILE5_30'],
        affected_fuzzy=['5-29', '5-30'],
        confidence=100,
        details=(
            'OSS-Fuzz report: '
            'https://bugs.chromium.org/p/oss-fuzz/issues/detail?id=1064\n\n'
            'Crash type: Heap-buffer-overflow READ 1\n'
            'Crash state:\ncdf_file_property_info\ncdf_file_summary_info\n'
            'cdf_check_summary_info\n'),
        ecosystem='',
        fixed='19ccebafb7663c422c714e0c67fa4775abf91c43',
        has_affected=True,
        issue_id='1064',
        project='file',
        public=True,
        reference_urls=[
            'https://bugs.chromium.org/p/oss-fuzz/issues/detail?id=1064'
        ],
        regressed='17ee4cf670c363de8d2ea4a4897d7a699837873f',
        repo_url='https://github.com/file/file.git',
        search_indices=['file', '2017-134', '2017', '134'],
        severity='MEDIUM',
        sort_key='2017-0000134',
        source_id='oss-fuzz:5417710252982272',
        source_of_truth=osv.SourceOfTruth.INTERNAL,
        status=1,
        summary='Heap-buffer-overflow in cdf_file_property_info',
        timestamp=datetime.datetime(2021, 1, 15, 0, 0, 24, 559102)).put()

  def tearDown(self):
    shutil.rmtree(self.tmp_dir, ignore_errors=True)

  @mock.patch('google.cloud.pubsub_v1.PublisherClient.publish')
  def test_basic(self, mock_publish):
    """Test basic run."""
    imp = importer.Importer('fake_public_key', 'fake_private_key', self.tmp_dir)
    imp.run()

    repo = pygit2.Repository(self.remote_source_repo_path)
    commit = repo.head.peel()

    self.assertEqual('infra@osv.dev', commit.author.email)
    self.assertEqual('OSV', commit.author.name)
    self.assertEqual('Import from OSS-Fuzz', commit.message)
    diff = repo.diff(commit.parents[0], commit)
    self.assertEqual(
        self._load_test_data('expected_patch_basic.diff'), diff.patch)

    mock_publish.assert_has_calls([
        mock.call(
            'projects/oss-vdb/topics/tasks',
            data=b'',
            original_sha256=('e3b0c44298fc1c149afbf4c8996fb924'
                             '27ae41e4649b934ca495991b7852b855'),
            path='2021-111.yaml',
            source='oss-fuzz',
            type='update')
    ])
    bug = osv.Bug.get_by_id('2017-134')
    self.assertEqual(osv.SourceOfTruth.SOURCE_REPO, bug.source_of_truth)

  @mock.patch('google.cloud.pubsub_v1.PublisherClient.publish')
  def test_scheduled_updates(self, mock_publish):
    """Test scheduled updates."""
    self.mock_repo.add_file('proj/OSV-2021-1337.yaml', '')
    self.mock_repo.add_file('proj/OSV-2021-1339.yaml', '')
    self.mock_repo.add_file('OSV-2021-1338.yaml', '')
    self.mock_repo.commit('OSV', 'infra@osv.dev')

    osv.Bug(
        id='2021-1337',
        project='proj',
        fixed='',
        status=1,
        source_id='oss-fuzz:123',
        source_of_truth=osv.SourceOfTruth.SOURCE_REPO,
        timestamp=datetime.datetime(2020, 1, 1, 0, 0, 0, 0)).put()
    osv.Bug(
        id='2021-1338',
        project='proj',
        fixed='fix',
        source_id='source:OSV-2021-1338.yaml',
        status=1,
        source_of_truth=osv.SourceOfTruth.SOURCE_REPO,
        timestamp=datetime.datetime.utcnow()).put()
    osv.Bug(
        id='2021-1339',
        project='proj',
        fixed='',
        status=1,
        source_id='oss-fuzz:124',
        source_of_truth=osv.SourceOfTruth.INTERNAL,
        timestamp=datetime.datetime(2020, 1, 1, 0, 0, 0, 0)).put()

    imp = importer.Importer('fake_public_key', 'fake_private_key', self.tmp_dir)
    imp.run()

    mock_publish.assert_has_calls([
        mock.call(
            'projects/oss-vdb/topics/tasks',
            data=b'',
            original_sha256=('e3b0c44298fc1c149afbf4c8996fb924'
                             '27ae41e4649b934ca495991b7852b855'),
            path='proj/OSV-2021-1337.yaml',
            source='oss-fuzz',
            type='update'),
        mock.call(
            'projects/oss-vdb/topics/tasks',
            allocated_id='2021-1339',
            data=b'',
            source_id='oss-fuzz:124',
            type='impact'),
        mock.call(
            'projects/oss-vdb/topics/tasks',
            data=b'',
            original_sha256=('e3b0c44298fc1c149afbf4c8996fb924'
                             '27ae41e4649b934ca495991b7852b855'),
            path='OSV-2021-1338.yaml',
            source='oss-fuzz',
            type='update'),
        mock.call(
            'projects/oss-vdb/topics/tasks',
            data=b'',
            original_sha256=('e3b0c44298fc1c149afbf4c8996fb924'
                             '27ae41e4649b934ca495991b7852b855'),
            path='2021-111.yaml',
            source='oss-fuzz',
            type='update')
    ])


if __name__ == '__main__':
  os.system('pkill -f datastore')
  ds_emulator = tests.start_datastore_emulator()
  try:
    with ndb.Client().context() as context:
      context.set_memcache_policy(False)
      context.set_cache_policy(False)
      unittest.main()
  finally:
    # TODO(ochang): Cleaner way of properly cleaning up processes.
    os.system('pkill -f datastore')
