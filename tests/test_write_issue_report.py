import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'write_issue_report.py'


GH_STUB = """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
log_path = os.environ.get('GH_CALL_LOG')
if log_path:
    with open(log_path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(args) + '\\n')

if os.environ.get('GH_FAIL_ALL') == '1':
    sys.stderr.write('gh forced failure\\n')
    sys.exit(int(os.environ.get('GH_FAIL_ALL_CODE', '1')))

if len(args) >= 2 and args[0] == 'issue' and args[1] == 'list':
    exit_code = int(os.environ.get('GH_ISSUE_LIST_EXIT', '0'))
    output = os.environ.get('GH_ISSUE_LIST_OUTPUT', '')
    if output:
        sys.stdout.write(output)
        if not output.endswith('\\n'):
            sys.stdout.write('\\n')
    if exit_code != 0:
        sys.stderr.write(os.environ.get('GH_ISSUE_LIST_ERROR', 'issue list failed'))
    sys.exit(exit_code)

if len(args) >= 3 and args[0] == 'issue' and args[1] == 'view':
    views_json = os.environ.get('GH_ISSUE_VIEWS_JSON', '{}')
    try:
        views = json.loads(views_json)
    except Exception:
        views = {}
    key = args[2]
    if key in views:
        value = views[key]
        if isinstance(value, str):
            sys.stdout.write(value)
        else:
            sys.stdout.write(json.dumps(value))
        sys.exit(0)
    sys.stderr.write('missing issue view for {}\\n'.format(key))
    sys.exit(1)

if len(args) >= 2 and args[0] == 'api':
    endpoint = args[1]
    responses_json = os.environ.get('GH_API_RESPONSES_JSON', '{}')
    try:
        responses = json.loads(responses_json)
    except Exception:
        responses = {}
    if endpoint in responses:
        value = responses[endpoint]
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    sys.stdout.write(item.rstrip('\\n') + '\\n')
                else:
                    sys.stdout.write(json.dumps(item) + '\\n')
        elif isinstance(value, str):
            sys.stdout.write(value)
            if value and not value.endswith('\\n'):
                sys.stdout.write('\\n')
        else:
            sys.stdout.write(json.dumps(value) + '\\n')
        sys.exit(0)
    sys.stderr.write('missing api response for {}\\n'.format(endpoint))
    sys.exit(1)

sys.stderr.write('unsupported gh call: {}\\n'.format(' '.join(args)))
sys.exit(1)
"""


GIT_STUB = """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
log_path = os.environ.get('GIT_CALL_LOG')
if log_path:
    with open(log_path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(args) + '\\n')

def int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default

if args and args[0] == 'clone':
    exit_code = int_env('GIT_CLONE_EXIT', 1)
    dest = pathlib.Path(args[-1])
    if exit_code == 0:
        dest.mkdir(parents=True, exist_ok=True)
    else:
        sys.stderr.write(os.environ.get('GIT_CLONE_ERROR', 'clone failed'))
    sys.exit(exit_code)

if len(args) >= 3 and args[0] == '-C' and args[2] == 'pull':
    exit_code = int_env('GIT_PULL_EXIT', 1)
    if exit_code != 0:
        sys.stderr.write(os.environ.get('GIT_PULL_ERROR', 'pull failed'))
    sys.exit(exit_code)

if len(args) >= 5 and args[0] == '-C' and args[2] == 'remote' and args[3] == 'set-url':
    sys.exit(int_env('GIT_REMOTE_SET_URL_EXIT', 0))

if len(args) >= 3 and args[0] == '-C' and args[2] == 'log':
    exit_code = int_env('GIT_LOG_EXIT', 1)
    out = os.environ.get('GIT_LOG_OUTPUT', '')
    if out:
        sys.stdout.write(out)
    if exit_code != 0:
        sys.stderr.write(os.environ.get('GIT_LOG_ERROR', 'log failed'))
    sys.exit(exit_code)

sys.exit(int_env('GIT_DEFAULT_EXIT', 0))
"""


class WriteIssueReportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix='write_issue_report_test.')
        self.work = Path(self.tmpdir.name)
        self.bin_dir = self.work / 'bin'
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self._write_executable(self.bin_dir / 'gh', GH_STUB)
        self._write_executable(self.bin_dir / 'git', GIT_STUB)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_executable(self, path, contents):
        path.write_text(contents, encoding='utf-8')
        path.chmod(0o755)

    def _run_script(
        self,
        input_text,
        *,
        input_name='gh_out.json',
        inactive_days='0',
        remove_label='weekly_forum',
        issue_hyperlink='no',
        repo_url='https://github.com/example/repo',
        extra_env=None,
    ):
        input_path = self.work / input_name
        input_path.write_text(input_text, encoding='utf-8')

        env = os.environ.copy()
        env['PATH'] = '{}{}{}'.format(self.bin_dir, os.pathsep, env.get('PATH', ''))
        env['GH_CALL_LOG'] = str(self.work / 'gh_calls.log')
        env['GIT_CALL_LOG'] = str(self.work / 'git_calls.log')
        if extra_env:
            env.update(extra_env)

        command = [
            sys.executable,
            str(SCRIPT_PATH),
            input_name,
            str(inactive_days),
            remove_label,
            issue_hyperlink,
            repo_url,
        ]
        return subprocess.run(
            command,
            cwd=self.work,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    def _read_text(self, relative_path):
        return (self.work / relative_path).read_text(encoding='utf-8')

    def _read_call_log(self, relative_path):
        path = self.work / relative_path
        if not path.exists():
            return []
        calls = []
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                calls.append(json.loads(line))
        return calls

    def test_rejects_invalid_boolean_argument(self):
        result = self._run_script('[]', issue_hyperlink='maybe')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid boolean value', result.stdout)

    def test_rejects_negative_inactive_days(self):
        result = self._run_script('[]', inactive_days='-1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inactive_days must be >= 0', result.stdout)

    def test_rejects_non_integer_inactive_days(self):
        result = self._run_script('[]', inactive_days='abc')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inactive_days must be an integer >= 0', result.stdout)

    def test_json_updated_at_is_treated_as_utc_not_local_timezone(self):
        updated_at = (datetime.datetime.utcnow() - datetime.timedelta(hours=23)).strftime('%Y-%m-%dT%H:%M:%SZ')
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': updated_at,
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            inactive_days='1',
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'TZ': 'Asia/Tokyo',
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 0', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')

    def test_json_updated_at_with_fractional_seconds_is_parsed(self):
        updated_at = (datetime.datetime.utcnow() - datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S') + '.123Z'
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': updated_at,
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            inactive_days='1',
            extra_env={'GH_ISSUE_LIST_EXIT': '1'},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 1', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice')

    def test_json_updated_at_with_lowercase_z_is_parsed(self):
        updated_at = (datetime.datetime.utcnow() - datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S') + 'z'
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': updated_at,
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            inactive_days='1',
            extra_env={'GH_ISSUE_LIST_EXIT': '1'},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 1', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice')

    def test_json_input_with_multiline_title_is_parsed(self):
        issues = [
            {
                'number': 10,
                'assignees': [{'login': 'alice'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/10',
                'title': 'line1\\nline2',
                'labels': [{'name': 'bug'}],
            },
            {
                'number': 20,
                'assignees': [],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/20',
                'title': 'normal',
                'labels': [],
            },
        ]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of open Issues: 2', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice')
        issue_report = self._read_text('issue_report.txt')
        self.assertIn('@alice:', issue_report)
        self.assertIn('#<span/>10', issue_report)

    def test_json_input_with_null_labels_is_parsed(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': None,
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of open Issues: 1', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice')

    def test_json_input_with_null_assignees_is_treated_as_unassigned(self):
        issues = [{
            'number': 42,
            'assignees': None,
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/42',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of open Issues: 1', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')
        report = self._read_text('issue_report.txt')
        self.assertIn('There are 1 unassigned issues.', report)
        self.assertIn('https://github.com/example/repo/issues/42', report)

    def test_json_input_with_dict_assignee_is_parsed(self):
        issues = [{
            'number': 1,
            'assignees': {'login': 'alice'},
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of open Issues: 1', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice')

    def test_case_variant_assignees_are_merged_without_losing_issues(self):
        issues = [
            {
                'number': 1,
                'assignees': [{'login': 'Alice'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/1',
                'title': 'x',
                'labels': [],
            },
            {
                'number': 2,
                'assignees': [{'login': 'alice'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/2',
                'title': 'y',
                'labels': [],
            },
        ]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'Alice')
        report = self._read_text('issue_report.txt')
        self.assertIn('@Alice:', report)
        self.assertNotIn('@alice:', report)
        self.assertIn('https://github.com/example/repo/issues/1', report)
        self.assertIn('https://github.com/example/repo/issues/2', report)

    def test_legacy_input_is_still_supported(self):
        legacy = '\n'.join([
            '1',
            'alice',
            '10 days ago',
            '1700000000',
            'legacy title',
            'https://github.com/example/repo/issues/1',
            'bug',
            '',
        ]) + '\n'
        result = self._run_script(legacy, input_name='gh_out.txt', issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('https://github.com/example/repo/issues/1', report)

    def test_legacy_assignees_without_space_after_comma_are_split(self):
        legacy = '\n'.join([
            '1',
            'alice,bob',
            '10 days ago',
            '1700000000',
            'legacy title',
            'https://github.com/example/repo/issues/1',
            'bug',
            '',
        ]) + '\n'
        result = self._run_script(legacy, input_name='gh_out.txt', issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), 'alice,bob')
        report = self._read_text('issue_report.txt')
        self.assertIn('@alice:', report)
        self.assertIn('@bob:', report)
        self.assertNotIn('@alice,bob:', report)

    def test_legacy_labels_without_space_after_comma_are_split_for_filtering(self):
        legacy = '\n'.join([
            '1',
            'alice',
            '10 days ago',
            '1700000000',
            'legacy title',
            'https://github.com/example/repo/issues/1',
            'bug,weekly_forum',
            '',
        ]) + '\n'
        result = self._run_script(legacy, input_name='gh_out.txt', issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 0', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')

    def test_repo_slug_strips_dot_git_for_api_calls(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://ghe.example.com/org/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [
                {
                    'id': 900,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                }
            ],
        }
        api_responses = {
            'repos/org/repo/issues/1/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
            'repos/org/repo/issues/comments/900/reactions': [
                {'created_at': '2026-02-09T03:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            repo_url='https://ghe.example.com/org/repo.git',
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertIn('repos/org/repo/issues/1/reactions', api_endpoints)
        self.assertIn('repos/org/repo/issues/comments/900/reactions', api_endpoints)
        self.assertFalse(any('.git/issues' in endpoint for endpoint in api_endpoints))

    def test_scan_is_skipped_when_no_inactive_assignees(self):
        issues = [{
            'number': 1,
            'assignees': [],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_OUTPUT': '1\n2\n'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Skipping contribution and reaction scan', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        self.assertFalse(any(call[:2] == ['issue', 'view'] for call in gh_calls))

    def test_comment_reaction_lookup_limit_is_enforced(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {'id': 1, 'createdAt': '2026-02-09T01:00:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
                {'id': 2, 'createdAt': '2026-02-09T01:10:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
                {'id': 3, 'createdAt': '2026-02-09T01:20:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
            ],
        }
        api_responses = {
            'repos/example/repo/issues/comments/1/reactions': [],
            'repos/example/repo/issues/comments/2/reactions': [],
            'repos/example/repo/issues/comments/3/reactions': [],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
                'MAX_COMMENT_REACTION_LOOKUPS': '2',
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Reached comment reaction lookup limit (2)', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        comment_api_calls = [
            call for call in gh_calls
            if len(call) >= 2 and call[0] == 'api' and '/issues/comments/' in call[1]
        ]
        self.assertEqual(len(comment_api_calls), 2)

    def test_assignee_report_filename_is_sanitized(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'bad/name'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.work / 'assignee_bad_name.txt').exists())

    def test_assignee_report_filename_collision_is_disambiguated(self):
        issues = [
            {
                'number': 1,
                'assignees': [{'login': 'a/b'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/1',
                'title': 'x',
                'labels': [],
            },
            {
                'number': 2,
                'assignees': [{'login': 'a?b'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/2',
                'title': 'y',
                'labels': [],
            },
        ]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)

        report_files = sorted(path.name for path in self.work.glob('assignee_a_b*.txt'))
        self.assertEqual(len(report_files), 2)
        self.assertIn('assignee_a_b.txt', report_files)
        self.assertTrue(any(name != 'assignee_a_b.txt' for name in report_files))

        report_contents = [(self.work / name).read_text(encoding='utf-8') for name in report_files]
        self.assertTrue(any('1,https://github.com/example/repo/issues/1' in text for text in report_contents))
        self.assertTrue(any('2,https://github.com/example/repo/issues/2' in text for text in report_contents))

    def test_assignee_query_links_are_url_encoded(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'Alice Bob'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('assignee%3AAlice%20Bob%20is%3Aopen', report)
        self.assertIn('mentions%3AAlice%20Bob', report)

    def test_wiki_remote_url_is_restored_after_token_use(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        (self.work / 'wiki_temp').mkdir(parents=True, exist_ok=True)
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GITHUB_TOKEN': 'token123',
                'GIT_PULL_EXIT': '1',
            },
        )
        self.assertEqual(result.returncode, 0)
        git_calls = self._read_call_log('git_calls.log')
        set_url_calls = [call for call in git_calls if len(call) >= 6 and call[2:4] == ['remote', 'set-url']]
        self.assertGreaterEqual(len(set_url_calls), 2)
        urls = [call[-1] for call in set_url_calls]
        self.assertTrue(any('x-access-token:token123@' in url for url in urls))
        self.assertTrue(any(url == 'https://github.com/example/repo.wiki.git' for url in urls))

    def test_missing_issue_url_uses_fallback(self):
        issues = [{
            'number': 7,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('https://github.com/example/repo/issues/7', report)

    def test_rejects_invalid_repo_url(self):
        result = self._run_script('[]', repo_url='invalid-repo-url')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid repository URL', result.stdout)

    def test_rejects_malformed_json_input(self):
        result = self._run_script('[{"number": 1}', input_name='gh_out.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Failed to parse issue JSON', result.stdout)

    def test_legacy_input_skips_malformed_rows(self):
        legacy = '\n'.join([
            'bad_number',
            'alice',
            '10 days ago',
            '1700000000',
            'legacy bad',
            'https://github.com/example/repo/issues/1',
            'bug',
            '',
            '2',
            'bob',
            '20 days ago',
            '1700000000',
            'legacy good',
            'https://github.com/example/repo/issues/2',
            'bug',
            '',
        ]) + '\n'
        result = self._run_script(legacy, input_name='gh_out.txt', issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Skipping malformed legacy issue row index 0', result.stdout)
        report = self._read_text('issue_report.txt')
        self.assertIn('https://github.com/example/repo/issues/2', report)
        self.assertNotIn('https://github.com/example/repo/issues/1', report)

    def test_non_numeric_and_duplicate_issue_list_entries_are_handled(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\nabc\n1\n2\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view, '2': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Non-numeric issue identifier from gh output: abc', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        issue_view_calls = [call for call in gh_calls if len(call) >= 3 and call[:2] == ['issue', 'view']]
        self.assertEqual(len(issue_view_calls), 2)
        self.assertEqual([call[2] for call in issue_view_calls], ['1', '2'])

    def test_invalid_comment_reaction_limit_falls_back_to_default(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {'id': 1, 'createdAt': '2026-02-09T01:00:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps({'repos/example/repo/issues/comments/1/reactions': []}),
                'MAX_COMMENT_REACTION_LOOKUPS': 'invalid',
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Invalid MAX_COMMENT_REACTION_LOOKUPS value', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        comment_api_calls = [
            call for call in gh_calls
            if len(call) >= 2 and call[0] == 'api' and '/issues/comments/' in call[1]
        ]
        self.assertEqual(len(comment_api_calls), 1)

    def test_negative_comment_reaction_limit_disables_lookups(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {'id': 1, 'createdAt': '2026-02-09T01:00:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'MAX_COMMENT_REACTION_LOOKUPS': '-3',
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Negative MAX_COMMENT_REACTION_LOOKUPS value', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        self.assertFalse(any(len(call) >= 2 and call[0] == 'api' and '/issues/comments/' in call[1] for call in gh_calls))

    def test_wiki_log_message_with_pipe_is_parsed(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = 'abc123|alice@users.noreply.github.com|2026-02-09|update A|B\nM\tMy-Page.md\n'
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('**[My Page](', report)
        self.assertIn('by alice', report)

    def test_wiki_log_message_with_tab_is_parsed(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|alice@users.noreply.github.com|2026-02-09|update\tA\nM\tTab-Page.md\n'
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('**[Tab Page](', report)
        self.assertIn('by alice', report)

    def test_json_input_requires_array_root(self):
        result = self._run_script('{"number": 1}', input_name='gh_out.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Expected JSON array', result.stdout)

    def test_malformed_issue_json_rows_are_skipped(self):
        issues = [
            {
                'number': 1,
                'assignees': [{'login': 'alice'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/1',
                'title': 'ok',
                'labels': [],
            },
            {
                'number': 'oops',
                'assignees': [{'login': 'alice'}],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/2',
                'title': 'bad',
                'labels': [],
            },
        ]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Skipping malformed issue JSON row index 1', result.stdout)
        self.assertIn('Number of open Issues: 1', result.stdout)
        report = self._read_text('issue_report.txt')
        self.assertIn('#<span/>1', report)
        self.assertNotIn('#<span/>2', report)

    def test_remove_label_excludes_inactive_issue_from_assignee_list(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [{'name': 'weekly_forum'}],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 0', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')

    def test_remove_label_filter_is_case_insensitive(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [{'name': 'Weekly_Forum'}],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 0', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')

    def test_remove_label_filter_accepts_string_labels_in_json_input(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': ['Weekly_Forum'],
        }]
        result = self._run_script(json.dumps(issues), extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        self.assertIn('Number of inactive Issues: 0', result.stdout)
        self.assertEqual(self._read_text('unique_assignees.txt').strip(), '')

    def test_issue_reaction_api_failure_is_non_fatal(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Could not fetch reactions for issue 1', result.stdout)

    def test_zero_count_reaction_groups_do_not_trigger_reaction_api_calls(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': [],
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 0}}],
            'comments': [
                {
                    'id': 1,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 0}}],
                }
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_calls = [call for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertEqual(api_calls, [])

    def test_weekly_forum_labeled_issue_is_excluded_from_reaction_scan(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view_forum = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': [{'name': 'Weekly_Forum'}],
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [
                {
                    'id': 1001,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                }
            ],
        }
        issue_view_regular = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': [{'name': 'bug'}],
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        api_responses = {
            'repos/example/repo/issues/200/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '100\n200\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'100': issue_view_forum, '200': issue_view_regular}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertNotIn('repos/example/repo/issues/100/reactions', api_endpoints)
        self.assertIn('repos/example/repo/issues/200/reactions', api_endpoints)
        report = self._read_text('issue_report.txt')
        self.assertIn('Thank you for your 1 contributions on 1 issues, writing in 0 wiki pages, and giving 1 reactions', report)

    def test_weekly_forum_string_labeled_issue_is_excluded_from_reaction_scan(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view_forum = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': ['Weekly_Forum'],
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        issue_view_regular = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': ['bug'],
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        api_responses = {
            'repos/example/repo/issues/200/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '100\n200\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'100': issue_view_forum, '200': issue_view_regular}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertNotIn('repos/example/repo/issues/100/reactions', api_endpoints)
        self.assertIn('repos/example/repo/issues/200/reactions', api_endpoints)

    def test_weekly_forum_dict_labeled_issue_is_excluded_from_reaction_scan(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view_forum = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': {'name': 'Weekly_Forum'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        issue_view_regular = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'labels': {'name': 'bug'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        api_responses = {
            'repos/example/repo/issues/200/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '100\n200\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'100': issue_view_forum, '200': issue_view_regular}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertNotIn('repos/example/repo/issues/100/reactions', api_endpoints)
        self.assertIn('repos/example/repo/issues/200/reactions', api_endpoints)

    def test_comment_reaction_api_failure_is_non_fatal(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {'id': 1, 'createdAt': '2026-02-09T01:00:00Z', 'author': {'login': 'alice'}, 'reactionGroups': [{'x': 1}]},
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Could not fetch reactions for comment 1', result.stdout)

    def test_comment_reaction_lookup_uses_database_id_when_comment_id_is_node_id(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {
                    'id': 'IC_kwDOxxxx',
                    'databaseId': 9001,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                },
            ],
        }
        api_responses = {
            'repos/example/repo/issues/comments/9001/reactions': [
                {'created_at': '2026-02-09T03:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertIn('repos/example/repo/issues/comments/9001/reactions', api_endpoints)
        self.assertFalse(any('IC_kwDOxxxx' in endpoint for endpoint in api_endpoints))

    def test_comment_reaction_lookup_uses_whitespace_padded_numeric_id(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {
                    'id': ' 9001 ',
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                },
            ],
        }
        api_responses = {
            'repos/example/repo/issues/comments/9001/reactions': [
                {'created_at': '2026-02-09T03:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertIn('repos/example/repo/issues/comments/9001/reactions', api_endpoints)

    def test_comment_reaction_lookup_uses_comment_url_when_numeric_id_missing(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {
                    'id': 'IC_kwDOyyyy',
                    'url': 'https://github.com/example/repo/issues/1#issuecomment-81234',
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                },
            ],
        }
        api_responses = {
            'repos/example/repo/issues/comments/81234/reactions': [
                {'created_at': '2026-02-09T03:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertIn('repos/example/repo/issues/comments/81234/reactions', api_endpoints)

    def test_comment_reaction_lookup_warns_when_no_numeric_comment_id_can_be_found(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {
                    'id': 'IC_kwDOzzzz',
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                },
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Could not determine numeric comment id for reaction lookup', result.stdout)
        gh_calls = self._read_call_log('gh_calls.log')
        comment_api_calls = [
            call for call in gh_calls
            if len(call) >= 2 and call[0] == 'api' and '/issues/comments/' in call[1]
        ]
        self.assertEqual(comment_api_calls, [])

    def test_issue_view_invalid_json_is_skipped(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': '{not json'}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Could not parse issue JSON for issue 1', result.stdout)

    def test_issue_view_with_non_object_payload_is_skipped(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': ['unexpected', 'shape']}),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('Unexpected issue payload type for issue 1', result.stdout)

    def test_issue_view_with_string_author_is_supported(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': 'alice',
            'reactionGroups': [],
            'comments': [],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('Thank you for your 1 contributions on 1 issues', report)

    def test_issue_view_with_string_comment_author_is_supported(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': [
                {
                    'id': 1,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': 'alice',
                    'reactionGroups': [],
                }
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('Thank you for your 2 contributions on 1 issues', report)

    def test_issue_view_with_non_list_comments_is_ignored(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [],
            'comments': {'unexpected': 'shape'},
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('@alice:', report)

    def test_wiki_contribution_counts_match_assignee_case_insensitively(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'Alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = 'abc123|alice@users.noreply.github.com|2026-02-09|wiki\nM\tLab-Notes.md\n'
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('writing in 1 wiki pages', report)

    def test_wiki_contribution_counts_multiple_authors_same_page_same_day(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}, {'login': 'bob'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = (
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|alice@users.noreply.github.com|2026-02-09|alice edit\n'
            'M\tShared-Page.md\n'
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|bob@users.noreply.github.com|2026-02-09|bob edit\n'
            'M\tShared-Page.md\n'
        )
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('@alice:', report)
        self.assertIn('@bob:', report)
        self.assertEqual(report.count('**[Shared Page]('), 1)
        self.assertEqual(report.count('writing in 1 wiki pages'), 2)

    def test_issue_and_reaction_contributions_match_assignee_case_insensitively(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'Alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [
                {
                    'id': 900,
                    'createdAt': '2026-02-09T01:00:00Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                }
            ],
        }
        api_responses = {
            'repos/example/repo/issues/1/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
            'repos/example/repo/issues/comments/900/reactions': [
                {'created_at': '2026-02-09T03:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('Thank you for your 2 contributions on 1 issues, writing in 0 wiki pages, and giving 2 reactions', report)

    def test_issue_and_reaction_fractional_timestamps_are_counted(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00.123Z',
            'author': {'login': 'alice'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [
                {
                    'id': 900,
                    'createdAt': '2026-02-09T01:00:00.456Z',
                    'author': {'login': 'alice'},
                    'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
                }
            ],
        }
        api_responses = {
            'repos/example/repo/issues/1/reactions': [
                {'created_at': '2026-02-09T02:00:00.100Z', 'user': {'login': 'alice'}}
            ],
            'repos/example/repo/issues/comments/900/reactions': [
                {'created_at': '2026-02-09T03:00:00.200Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('Thank you for your 2 contributions on 1 issues, writing in 0 wiki pages, and giving 2 reactions', report)

    def test_unassigned_issue_summary_lists_issue_when_present(self):
        issues = [{
            'number': 42,
            'assignees': [],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/42',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('There are 1 unassigned issues.', report)
        self.assertIn('https://github.com/example/repo/issues/42', report)

    def test_unassigned_issue_summary_excludes_remove_label_issues_case_insensitively(self):
        issues = [
            {
                'number': 42,
                'assignees': [],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/42',
                'title': 'forum',
                'labels': [{'name': 'Weekly_Forum'}],
            },
            {
                'number': 43,
                'assignees': [],
                'updatedAt': '2026-01-01T00:00:00Z',
                'url': 'https://github.com/example/repo/issues/43',
                'title': 'regular',
                'labels': [{'name': 'bug'}],
            },
        ]
        result = self._run_script(json.dumps(issues), issue_hyperlink='yes', extra_env={'GH_ISSUE_LIST_EXIT': '1'})
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('There are 1 unassigned issues.', report)
        self.assertIn('https://github.com/example/repo/issues/43', report)
        self.assertNotIn('https://github.com/example/repo/issues/42', report)

    def test_repo_slug_supports_ssh_repo_url(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/org/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        issue_view = {
            'createdAt': '2026-02-09T00:00:00Z',
            'author': {'login': 'alice'},
            'reactionGroups': [{'content': 'THUMBS_UP', 'users': {'totalCount': 1}}],
            'comments': [],
        }
        api_responses = {
            'repos/org/repo/issues/1/reactions': [
                {'created_at': '2026-02-09T02:00:00Z', 'user': {'login': 'alice'}}
            ],
        }
        result = self._run_script(
            json.dumps(issues),
            repo_url='git@github.com:org/repo.git',
            extra_env={
                'GH_ISSUE_LIST_OUTPUT': '1\n',
                'GH_ISSUE_VIEWS_JSON': json.dumps({'1': issue_view}),
                'GH_API_RESPONSES_JSON': json.dumps(api_responses),
                'GIT_CLONE_EXIT': '1',
            },
        )
        self.assertEqual(result.returncode, 0)
        gh_calls = self._read_call_log('gh_calls.log')
        api_endpoints = [call[1] for call in gh_calls if len(call) >= 2 and call[0] == 'api']
        self.assertIn('repos/org/repo/issues/1/reactions', api_endpoints)

    def test_dot_git_repo_url_uses_clean_web_links_and_wiki_clone_url(self):
        issues = [{
            'number': 7,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            issue_hyperlink='yes',
            repo_url='https://github.com/example/repo.git',
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('https://github.com/example/repo/issues/7', report)
        self.assertNotIn('repo.git/issues/7', report)
        self.assertIn('https://github.com/example/repo/issues?q=assignee%3Aalice%20is%3Aopen', report)

        git_calls = self._read_call_log('git_calls.log')
        clone_calls = [call for call in git_calls if call[:1] == ['clone']]
        self.assertTrue(clone_calls)
        self.assertEqual(clone_calls[0][1], 'https://github.com/example/repo.wiki.git')

    def test_ssh_repo_url_uses_https_web_links_and_ssh_wiki_clone_url(self):
        issues = [{
            'number': 8,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'title': 'x',
            'labels': [],
        }]
        result = self._run_script(
            json.dumps(issues),
            issue_hyperlink='yes',
            repo_url='git@github.com:org/repo.git',
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('https://github.com/org/repo/issues/8', report)
        self.assertNotIn('git@github.com:org/repo.git/issues/8', report)
        self.assertIn('https://github.com/org/repo/issues?q=assignee%3Aalice%20is%3Aopen', report)

        git_calls = self._read_call_log('git_calls.log')
        clone_calls = [call for call in git_calls if call[:1] == ['clone']]
        self.assertTrue(clone_calls)
        self.assertEqual(clone_calls[0][1], 'git@github.com:org/repo.wiki.git')

    def test_wiki_rename_status_is_counted_as_updated_page(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = (
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|alice@users.noreply.github.com|2026-02-09|rename\n'
            'R100\tOld-Page.md\tNew-Page.md\n'
        )
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('**[New Page](', report)
        self.assertIn('Updated on 2026-02-09 by alice', report)
        self.assertIn('writing in 1 wiki pages', report)

    def test_wiki_copy_status_is_counted_as_updated_page(self):
        issues = [{
            'number': 1,
            'assignees': [{'login': 'alice'}],
            'updatedAt': '2026-01-01T00:00:00Z',
            'url': 'https://github.com/example/repo/issues/1',
            'title': 'x',
            'labels': [],
        }]
        git_log_output = (
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|alice@users.noreply.github.com|2026-02-09|copy\n'
            'C100\tOld-Page.md\tCopied-Page.md\n'
        )
        result = self._run_script(
            json.dumps(issues),
            extra_env={
                'GH_ISSUE_LIST_EXIT': '1',
                'GIT_CLONE_EXIT': '0',
                'GIT_LOG_EXIT': '0',
                'GIT_LOG_OUTPUT': git_log_output,
            },
        )
        self.assertEqual(result.returncode, 0)
        report = self._read_text('issue_report.txt')
        self.assertIn('**[Copied Page](', report)
        self.assertIn('Updated on 2026-02-09 by alice', report)
        self.assertIn('writing in 1 wiki pages', report)


if __name__ == '__main__':
    unittest.main()
