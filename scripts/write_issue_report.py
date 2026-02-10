import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse


def parse_bool(value):
    if isinstance(value, bool):
        return value
    value_lower = str(value).strip().lower()
    if value_lower in ('1', 'true', 't', 'yes', 'y', 'on'):
        return True
    if value_lower in ('0', 'false', 'f', 'no', 'n', 'off'):
        return False
    raise ValueError('Invalid boolean value: {}'.format(value))


def repo_slug_from_url(repo_url):
    cleaned = repo_url.strip().rstrip('/')

    def normalize_slug(raw_slug):
        slug = raw_slug.strip().strip('/')
        if slug.endswith('.git'):
            slug = slug[:-4]
        parts = [part for part in slug.split('/') if part]
        if len(parts) != 2:
            raise ValueError('Invalid repository URL: {}'.format(repo_url))
        return '/'.join(parts)

    if cleaned.startswith('git@'):
        if ':' not in cleaned:
            raise ValueError('Invalid repository URL: {}'.format(repo_url))
        return normalize_slug(cleaned.split(':', 1)[1])

    if '://' in cleaned:
        remainder = cleaned.split('://', 1)[1]
        if '/' not in remainder:
            raise ValueError('Invalid repository URL: {}'.format(repo_url))
        return normalize_slug(remainder.split('/', 1)[1])

    if '/' not in cleaned:
        raise ValueError('Invalid repository URL: {}'.format(repo_url))
    return normalize_slug(cleaned)


def format_relative_elapsed(elapsed_sec):
    if elapsed_sec < 60:
        return '{:.0f} seconds ago'.format(elapsed_sec)
    if elapsed_sec < 3600:
        return '{:.1f} minutes ago'.format(elapsed_sec / 60.0)
    if elapsed_sec < 86400:
        return '{:.1f} hours ago'.format(elapsed_sec / 3600.0)
    return '{:.1f} days ago'.format(elapsed_sec / 86400.0)


def safe_filename_component(value):
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', value)
    if safe == '':
        return 'unknown'
    return safe


def unique_filename_components(values):
    used = set()
    used_folded = set()
    filename_map = {}

    for value in values:
        base = safe_filename_component(value)
        candidate = base
        candidate_folded = candidate.lower()
        if candidate_folded in used_folded:
            suffix = hashlib.sha1(value.encode('utf-8')).hexdigest()[:8]
            candidate = '{}_{}'.format(base, suffix)
            candidate_folded = candidate.lower()
            collision_index = 2
            while candidate_folded in used_folded:
                candidate = '{}_{}_{}'.format(base, suffix, collision_index)
                candidate_folded = candidate.lower()
                collision_index += 1

        used.add(candidate)
        used_folded.add(candidate_folded)
        filename_map[value] = candidate

    return filename_map


def unique_case_insensitive(values):
    canonical = {}
    for value in values:
        key = value.lower()
        if key not in canonical:
            canonical[key] = value
    return [canonical[key] for key in sorted(canonical.keys())]


def parse_legacy_csv_field(raw_value):
    values = [value.strip() for value in raw_value.split(',')]
    values = [value for value in values if value != '']
    if values:
        return values
    return ['']


def extract_assignee_logins(raw_assignees):
    if isinstance(raw_assignees, (dict, str)):
        raw_assignees = [raw_assignees]
    elif not isinstance(raw_assignees, list):
        return ['']

    assignees = []
    for assignee in raw_assignees:
        login = None
        if isinstance(assignee, dict):
            login = assignee.get('login')
        elif isinstance(assignee, str):
            login = assignee

        if isinstance(login, str):
            login = login.strip()
            if login != '':
                assignees.append(login)

    if assignees:
        return assignees
    return ['']


def extract_login(raw_user):
    login = None
    if isinstance(raw_user, dict):
        login = raw_user.get('login')
    elif isinstance(raw_user, str):
        login = raw_user

    if isinstance(login, str):
        login = login.strip()
        if login != '':
            return login
    return None


def extract_label_names(raw_labels):
    if isinstance(raw_labels, (dict, str)):
        raw_labels = [raw_labels]
    elif not isinstance(raw_labels, list):
        return []

    labels = []
    for label in raw_labels:
        if isinstance(label, dict):
            name = label.get('name')
            if isinstance(name, str):
                name = name.strip()
                if name != '':
                    labels.append(name)
        elif isinstance(label, str):
            name = label.strip()
            if name != '':
                labels.append(name)
    return labels


def parse_github_timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')

    text = value.strip()
    if text == '':
        raise ValueError('timestamp is empty')

    if text.endswith('Z') or text.endswith('z'):
        text = text[:-1] + '+00:00'

    dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def query_url(repo_url, query):
    return '{}{}'.format(repo_url + '/issues?q=', urllib.parse.quote(query, safe=''))


def has_label_case_insensitive(labels, target_label):
    if target_label == '':
        return False
    for label in labels:
        if str(label).strip().lower() == target_label:
            return True
    return False


def has_positive_reactions(reaction_summary):
    if not reaction_summary:
        return False

    if isinstance(reaction_summary, dict):
        total_count = reaction_summary.get('totalCount')
        if isinstance(total_count, int):
            return total_count > 0
        int_values = [value for value in reaction_summary.values() if isinstance(value, int)]
        if int_values:
            return any(value > 0 for value in int_values)
        # Unknown dict structure: keep behavior conservative and do lookup.
        return True

    if isinstance(reaction_summary, list):
        saw_unknown_shape = False
        saw_count = False
        for group in reaction_summary:
            if not isinstance(group, dict):
                saw_unknown_shape = True
                continue

            users = group.get('users')
            if isinstance(users, dict):
                users_total = users.get('totalCount')
                if isinstance(users_total, int):
                    saw_count = True
                    if users_total > 0:
                        return True
                    continue

            total_count = group.get('totalCount')
            if isinstance(total_count, int):
                saw_count = True
                if total_count > 0:
                    return True
                continue

            saw_unknown_shape = True

        if saw_count and not saw_unknown_shape:
            return False
        return saw_unknown_shape

    return bool(reaction_summary)


def extract_comment_reaction_id(comment):
    for key in ('databaseId', 'database_id', 'id'):
        value = comment.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value_stripped = value.strip()
            if value_stripped.isdigit():
                return int(value_stripped)

    for key in ('url', 'html_url'):
        value = comment.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r'issuecomment-(\d+)', value)
        if match:
            return int(match.group(1))
        match = re.search(r'/issues/comments/(\d+)', value)
        if match:
            return int(match.group(1))

    return None


def repo_web_url_from_input(repo_url, repo_slug):
    cleaned = repo_url.strip().rstrip('/')
    if cleaned.startswith('git@'):
        host = cleaned.split('@', 1)[1].split(':', 1)[0]
        return 'https://{}/{}'.format(host, repo_slug)
    if '://' in cleaned:
        parsed = urllib.parse.urlsplit(cleaned)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError('Invalid repository URL: {}'.format(repo_url))
        return '{}://{}/{}'.format(parsed.scheme, parsed.netloc, repo_slug)
    return 'https://github.com/{}'.format(repo_slug)


def wiki_git_url_from_input(repo_url, repo_slug):
    cleaned = repo_url.strip().rstrip('/')
    if cleaned.startswith('git@'):
        host = cleaned.split('@', 1)[1].split(':', 1)[0]
        return 'git@{}:{}.wiki.git'.format(host, repo_slug)
    if '://' in cleaned:
        parsed = urllib.parse.urlsplit(cleaned)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError('Invalid repository URL: {}'.format(repo_url))
        return '{}://{}/{}.wiki.git'.format(parsed.scheme, parsed.netloc, repo_slug)
    return 'https://github.com/{}.wiki.git'.format(repo_slug)


print('Starting write_issue_report.py')

if len(sys.argv) != 6:
    raise SystemExit('Usage: write_issue_report.py <gh_out_file> <inactive_days> <remove_label> <issue_hyperlink yes/no> <repo_url>')

hub_out_file = sys.argv[1]
try:
    since_last_updated_day = int(sys.argv[2])
except ValueError:
    raise SystemExit('inactive_days must be an integer >= 0')
if since_last_updated_day < 0:
    raise SystemExit('inactive_days must be >= 0')
remove_label = sys.argv[3]
remove_label_normalized = remove_label.strip().lower()
try:
    generate_issue_hyperlink = parse_bool(sys.argv[4])
except ValueError as exc:
    raise SystemExit(str(exc))
repo_url = sys.argv[5]
try:
    repo_slug = repo_slug_from_url(repo_url)
except ValueError as exc:
    raise SystemExit(str(exc))
try:
    repo_web_url = repo_web_url_from_input(repo_url, repo_slug)
    wiki_url_public = wiki_git_url_from_input(repo_url, repo_slug)
except ValueError as exc:
    raise SystemExit(str(exc))

since_last_updated_sec = since_last_updated_day * 86400

with open(hub_out_file, 'r') as f:
    hub_txt = f.read()

hub_txt = hub_txt.lstrip('\ufeff')
issues = list()
hub_txt_stripped = hub_txt.lstrip()
if hub_txt_stripped.startswith('[') or hub_txt_stripped.startswith('{'):
    try:
        issue_records = json.loads(hub_txt)
    except json.JSONDecodeError as exc:
        raise SystemExit('Failed to parse issue JSON from {}: {}'.format(hub_out_file, exc))
    if not isinstance(issue_records, list):
        raise SystemExit('Expected JSON array in {}'.format(hub_out_file))
    now_ts = time.time()
    for i, issue_record in enumerate(issue_records):
        try:
            issue_number = int(issue_record['number'])
            updated_at = issue_record['updatedAt']
            updated_dt = parse_github_timestamp(updated_at)
            unix_timestamp_updated = int(updated_dt.replace(tzinfo=datetime.timezone.utc).timestamp())
            assignees = extract_assignee_logins(issue_record.get('assignees', []))
            labels = extract_label_names(issue_record.get('labels', []))
            if not labels:
                labels = ['']
            issue_title = issue_record.get('title', '')
            issue_url = issue_record.get('url', '')
            if not issue_url:
                issue_url = '{}/issues/{}'.format(repo_web_url, issue_number)
        except (KeyError, TypeError, ValueError) as exc:
            print('Warning: Skipping malformed issue JSON row index {}: {}'.format(i, exc))
            continue
        issues.append({
            'issue_number': issue_number,
            'assignees': assignees,
            'relative_time_updated': format_relative_elapsed(max(0.0, now_ts - unix_timestamp_updated)),
            'unix_timestamp_updated': unix_timestamp_updated,
            'issue_title': issue_title,
            'issue_url': issue_url,
            'labels': labels
        })
else:
    hub_items = hub_txt.split('\n')
    if hub_items[len(hub_items)-1]=='':
        hub_items = hub_items[0:(len(hub_items)-1)]
    num_item = 8
    if (len(hub_items) % num_item) != 0:
        print('Warning: Unexpected legacy gh_out format ({} lines, expected multiple of {}). Trailing lines will be ignored.'.format(len(hub_items), num_item))
    num_open_issue = len(hub_items) // num_item
    for i in range(num_open_issue):
        issue_items = hub_items[i*num_item:(i+1)*num_item]
        try:
            issue_number = int(issue_items[0])
            unix_timestamp_updated = int(issue_items[3])
            assignees = parse_legacy_csv_field(issue_items[1])
            labels = parse_legacy_csv_field(issue_items[6])
        except (IndexError, ValueError):
            print('Warning: Skipping malformed legacy issue row index {}'.format(i))
            continue
        issue_url = issue_items[5]
        if not issue_url:
            issue_url = '{}/issues/{}'.format(repo_web_url, issue_number)
        issues.append({
            'issue_number': issue_number,
            'assignees': assignees,
            'relative_time_updated': issue_items[2],
            'unix_timestamp_updated': unix_timestamp_updated,
            'issue_title': issue_items[4],
            'issue_url': issue_url,
            'labels': labels
        })

print('Number of open Issues: {:,}'.format(len(issues)))
if not generate_issue_hyperlink:
    print('Issue hyperlinks will not be generated.')
    for i in range(len(issues)):
        # https://github.com/hackmdio/hackmd-io-issues/issues/261
        issues[i]['issue_url'] = re.sub('.*/', '#<span/>', issues[i]['issue_url'])

inactive_issues = [ issue for issue in issues if (time.time()-issue['unix_timestamp_updated']) > since_last_updated_sec ]
inactive_issues = [ issue for issue in inactive_issues if not has_label_case_insensitive(issue['labels'], remove_label_normalized) ]
print('Number of inactive Issues: {:,}'.format(len(inactive_issues)))

assignee_candidates = [assignee.strip() for issue in inactive_issues for assignee in issue['assignees'] if assignee.strip() != '']
unique_assignees = unique_case_insensitive(assignee_candidates)
print('Number of assignees in inactive Issues: {:,}'.format(len(unique_assignees)))
assignee_filename_map = unique_filename_components(unique_assignees)
unique_assignee_txt = ','.join(unique_assignees)
with open('unique_assignees.txt', 'w') as f:
    f.write(unique_assignee_txt + '\n')

# Clean up stale per-assignee summaries before writing fresh ones
for assignee_file in glob.glob('assignee_*.txt'):
    try:
        os.remove(assignee_file)
    except OSError as exc:
        print('Failed to remove {}: {}'.format(assignee_file, exc))

# Member-wise contributions in the last X days
num_day = 7
today = datetime.datetime.utcnow()
today_str = today.strftime('%Y-%m-%d')
startday = datetime.datetime.utcnow() - datetime.timedelta(days=num_day)
startday_str = startday.strftime('%Y-%m-%d')
gh_command1 = [
    'gh', 'issue', 'list',
    '--limit', str(100000),
    '--state', 'all',
    '--search', 'updated:{}..{}'.format(startday_str, today_str),
    '--json', 'number',
    '--jq', '.[].number'
]
gh_command1_str = ' '.join(gh_command1)
print('gh command: {}'.format(gh_command1_str))
gh_out1 = subprocess.run(gh_command1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
recent_issue_nums = []
if gh_out1.returncode != 0:
    print('Warning: gh command failed: {}'.format(gh_out1.stderr.decode('utf8').strip()))
else:
    for rin in gh_out1.stdout.decode('utf8').split('\n'):
        rin = rin.strip()
        if rin == '':
            continue
        if rin.isdigit():
            recent_issue_nums.append(int(rin))
        else:
            print('Warning: Non-numeric issue identifier from gh output: {}'.format(rin))
recent_issue_nums = list(dict.fromkeys(recent_issue_nums))
print('Issues updated in the last {:,} days: {}'.format(num_day, ', '.join([ str(r) for r in recent_issue_nums ])))
recent_contributions = dict()
# Create case-insensitive lookup map for matching wiki authors and reactors
assignee_lookup = {}
for assignee in unique_assignees:
    assignee_lookup.setdefault(assignee.lower(), assignee)
for assignee in unique_assignees:
    recent_contributions[assignee] = dict()
    recent_contributions[assignee]['issue_numbers'] = list()
    recent_contributions[assignee]['timestamps'] = list()
    recent_contributions[assignee]['wiki_pages'] = set()
    recent_contributions[assignee]['reactions_given'] = 0
    recent_contributions[assignee]['reactions_received'] = 0
comment_reaction_lookup_count = 0
max_comment_reaction_lookups = 500
max_comment_reaction_lookups_env = os.environ.get('MAX_COMMENT_REACTION_LOOKUPS', '')
if max_comment_reaction_lookups_env != '':
    try:
        max_comment_reaction_lookups = int(max_comment_reaction_lookups_env)
    except ValueError:
        print('Warning: Invalid MAX_COMMENT_REACTION_LOOKUPS value: {}. Using default {}.'.format(max_comment_reaction_lookups_env, max_comment_reaction_lookups))
if max_comment_reaction_lookups < 0:
    print('Warning: Negative MAX_COMMENT_REACTION_LOOKUPS value: {}. Using 0.'.format(max_comment_reaction_lookups))
    max_comment_reaction_lookups = 0
comment_reaction_limit_warned = False
comment_reaction_id_warned = False
scan_issue_nums = recent_issue_nums
max_recent_issues_to_scan = 2000
if len(scan_issue_nums) > max_recent_issues_to_scan:
    print('Warning: Trimming recent issue scan from {:,} to {:,} issues.'.format(len(scan_issue_nums), max_recent_issues_to_scan))
    scan_issue_nums = scan_issue_nums[:max_recent_issues_to_scan]
if not unique_assignees:
    if recent_issue_nums:
        print('No assignees in inactive issues. Skipping contribution and reaction scan.')
    scan_issue_nums = []
for issue_num in scan_issue_nums:
    gh_command2 = ['gh', 'issue', 'view', str(issue_num), '--json', 'assignees,author,body,closed,closedAt,comments,createdAt,id,labels,milestone,number,reactionGroups,state,title,updatedAt,url']
    gh_out2 = subprocess.run(gh_command2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if gh_out2.returncode != 0:
        print('gh command failed (issue {}): {}'.format(issue_num, gh_out2.stderr.decode('utf8').strip()))
        continue
    try:
        issue = json.loads(gh_out2.stdout.decode('utf8'))
    except json.JSONDecodeError:
        print('Warning: Could not parse issue JSON for issue {}'.format(issue_num))
        continue
    if not isinstance(issue, dict):
        print('Warning: Unexpected issue payload type for issue {}: {}'.format(issue_num, type(issue).__name__))
        continue
    issue_created_at_raw = issue.get('createdAt')
    if not issue_created_at_raw:
        print('Warning: Missing createdAt for issue {}'.format(issue_num))
        continue
    try:
        issue_created_at = parse_github_timestamp(issue_created_at_raw)
    except ValueError:
        print('Warning: Invalid createdAt for issue {}: {}'.format(issue_num, issue_created_at_raw))
        continue
    issue_author = extract_login(issue.get('author'))
    issue_labels = extract_label_names(issue.get('labels', []))
    if has_label_case_insensitive(issue_labels, remove_label_normalized):
        print('Skipping issue {} from contribution scan because it has label {}'.format(issue_num, remove_label))
        continue
    matched_issue_author = assignee_lookup.get(issue_author.lower()) if issue_author else None
    if (issue_created_at > startday) and matched_issue_author:
        recent_contributions[matched_issue_author]['issue_numbers'].append(issue_num)
        recent_contributions[matched_issue_author]['timestamps'].append(issue_created_at)
    
    # Track reactions on the issue itself
    if has_positive_reactions(issue.get('reactionGroups')):
        # Get detailed reaction info to see who reacted
        gh_command_reactions = ['gh', 'api', 'repos/{}/issues/{}/reactions'.format(repo_slug, issue_num), '--paginate', '--jq', '.[]']
        gh_out_reactions = subprocess.run(gh_command_reactions, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if gh_out_reactions.returncode == 0:
            # Parse newline-delimited JSON objects from --jq '.[]'
            reactions = []
            for line in gh_out_reactions.stdout.decode('utf8').strip().split('\n'):
                if line.strip():
                    try:
                        reactions.append(json.loads(line))
                    except json.JSONDecodeError:
                        print('Warning: Could not parse reaction JSON: {}'.format(line[:100]))
            if reactions:
                print('Found {} reactions on issue {}'.format(len(reactions), issue_num))
            for reaction in reactions:
                reaction_created_at_raw = reaction.get('created_at')
                if not reaction_created_at_raw:
                    continue
                try:
                    reaction_created_at = parse_github_timestamp(reaction_created_at_raw)
                except ValueError:
                    continue
                reactor = extract_login(reaction.get('user'))
                if (reaction_created_at > startday) and reactor:
                    matched_reactor = assignee_lookup.get(reactor.lower())
                    # Count reactions given
                    if matched_reactor:
                        recent_contributions[matched_reactor]['reactions_given'] += 1
                    # Count reactions received by issue author
                    if matched_issue_author:
                        recent_contributions[matched_issue_author]['reactions_received'] += 1
        else:
            print('Warning: Could not fetch reactions for issue {}: {}'.format(issue_num, gh_out_reactions.stderr.decode('utf8').strip()))
    
    raw_comments = issue.get('comments')
    if not isinstance(raw_comments, list):
        raw_comments = []

    for comment in raw_comments:
        if not isinstance(comment, dict):
            continue
        comment_created_at_raw = comment.get('createdAt')
        if not comment_created_at_raw:
            continue
        try:
            comment_created_at = parse_github_timestamp(comment_created_at_raw)
        except ValueError:
            continue
        comment_author = extract_login(comment.get('author'))
        matched_comment_author = assignee_lookup.get(comment_author.lower()) if comment_author else None
        if (comment_created_at > startday) and matched_comment_author:
            recent_contributions[matched_comment_author]['issue_numbers'].append(issue_num)
            recent_contributions[matched_comment_author]['timestamps'].append(comment_created_at)
        
        # Track reactions on comments
        has_comment_reactions = (
            has_positive_reactions(comment.get('reactions')) or
            has_positive_reactions(comment.get('reactionGroups'))
        )
        comment_id = extract_comment_reaction_id(comment)
        if has_comment_reactions and comment_id is not None:
            if comment_reaction_lookup_count >= max_comment_reaction_lookups:
                if not comment_reaction_limit_warned:
                    print('Warning: Reached comment reaction lookup limit ({:,}). Skipping remaining comment reaction lookups.'.format(max_comment_reaction_lookups))
                    comment_reaction_limit_warned = True
                continue
            comment_reaction_lookup_count += 1
            # Note: comment reactions are included in the issue view JSON, but we need to check if they have the detailed user info
            # The reactionGroups in comments may not have user details, so we'll need to make an API call
            gh_command_comment_reactions = ['gh', 'api', 'repos/{}/issues/comments/{}/reactions'.format(repo_slug, comment_id), '--paginate', '--jq', '.[]']
            gh_out_comment_reactions = subprocess.run(gh_command_comment_reactions, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if gh_out_comment_reactions.returncode == 0:
                # Parse newline-delimited JSON objects from --jq '.[]'
                comment_reactions = []
                for line in gh_out_comment_reactions.stdout.decode('utf8').strip().split('\n'):
                    if line.strip():
                        try:
                            comment_reactions.append(json.loads(line))
                        except json.JSONDecodeError:
                            print('Warning: Could not parse comment reaction JSON: {}'.format(line[:100]))
                for reaction in comment_reactions:
                    reaction_created_at_raw = reaction.get('created_at')
                    if not reaction_created_at_raw:
                        continue
                    try:
                        reaction_created_at = parse_github_timestamp(reaction_created_at_raw)
                    except ValueError:
                        continue
                    reactor = extract_login(reaction.get('user'))
                    if (reaction_created_at > startday) and reactor:
                        matched_reactor = assignee_lookup.get(reactor.lower())
                        # Count reactions given
                        if matched_reactor:
                            recent_contributions[matched_reactor]['reactions_given'] += 1
                        # Count reactions received by comment author
                        if matched_comment_author:
                            recent_contributions[matched_comment_author]['reactions_received'] += 1
            else:
                print('Warning: Could not fetch reactions for comment {}: {}'.format(comment_id, gh_out_comment_reactions.stderr.decode('utf8').strip()))
        elif has_comment_reactions:
            if not comment_reaction_id_warned:
                print('Warning: Could not determine numeric comment id for reaction lookup. Skipping affected comments.')
                comment_reaction_id_warned = True
for assignee in unique_assignees:
    recent_contributions[assignee]['num_issue'] = len(set(recent_contributions[assignee]['issue_numbers']))
    recent_contributions[assignee]['num_comment'] = len(recent_contributions[assignee]['issue_numbers'])

# Get Wiki updates from the last week
wiki_pages = []
try:
    # Clone or update the wiki repository
    wiki_dir = 'wiki_temp'
    wiki_url = wiki_url_public
    github_token = os.environ.get('GITHUB_TOKEN')
    if github_token and wiki_url.startswith('https://'):
        wiki_url = wiki_url.replace('https://', 'https://x-access-token:{}@'.format(github_token), 1)
    
    if os.path.exists(wiki_dir):
        # Update existing wiki clone
        print('Updating existing wiki repository...')
        if github_token:
            subprocess.run(['git', '-C', wiki_dir, 'remote', 'set-url', 'origin', wiki_url], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pull_result = subprocess.run(['git', '-C', wiki_dir, 'pull'], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if github_token:
            subprocess.run(['git', '-C', wiki_dir, 'remote', 'set-url', 'origin', wiki_url_public], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if pull_result.returncode != 0:
            print('Warning: Could not update wiki repository: {}'.format(pull_result.stderr.decode('utf8').strip()))
    else:
        # Clone the wiki repository
        print('Cloning wiki repository from {}...'.format(wiki_url_public))
        result = subprocess.run(['git', 'clone', wiki_url, wiki_dir], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print('Warning: Could not clone wiki repository: {}'.format(result.stderr.decode('utf8').strip()))
        elif github_token:
            subprocess.run(['git', '-C', wiki_dir, 'remote', 'set-url', 'origin', wiki_url_public], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if os.path.exists(wiki_dir):
        # Get commits from the last 7 days with affected files
        since_date = startday.strftime('%Y-%m-%d')
        git_log_cmd = ['git', '-C', wiki_dir, 'log', '--since={}'.format(since_date), '--name-status', '--pretty=format:%H|%ae|%ad|%s', '--date=short']
        result = subprocess.run(git_log_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            log_output = result.stdout.decode('utf8')
            lines = log_output.strip().split('\n')
            
            current_commit = None
            seen_pages = set()
            
            for line in lines:
                if re.match(r'^[0-9a-fA-F]{6,40}\|', line):
                    # This is a commit line
                    parts = line.split('|', 3)
                    if len(parts) >= 4:
                        author_email = parts[1]
                        
                        # Try to extract GitHub username from email
                        author_username = None
                        if '@users.noreply.github.com' in author_email:
                            # GitHub noreply email format: username@users.noreply.github.com or ID+username@users.noreply.github.com
                            email_part = author_email.split('@')[0]
                            if '+' in email_part:
                                author_username = email_part.split('+')[1]
                            else:
                                author_username = email_part
                        
                        # If we couldn't extract from email, use the full email for display
                        if not author_username:
                            author_username = author_email.split('@')[0]
                        
                        current_commit = {
                            'hash': parts[0],
                            'author': author_username,
                            'author_email': author_email,
                            'date': parts[2],
                            'message': parts[3]
                        }
                elif line.strip() and current_commit:
                    # This is a file change line (e.g., "M Page-Name.md" or "A New-Page.md")
                    parts = line.strip().split('\t')
                    if len(parts) >= 2:
                        status = parts[0]  # A (added), M (modified), D (deleted)
                        filename = parts[-1] if (status.startswith('R') or status.startswith('C')) and len(parts) >= 3 else parts[1]
                        
                        # Convert filename to wiki page name (remove .md extension)
                        if filename.endswith('.md'):
                            page_name = filename[:-3].replace('-', ' ')
                            page_key = (page_name, current_commit['date'])
                            is_page_update = (status in ['A', 'M'] or status.startswith('R') or status.startswith('C'))
                            if is_page_update:
                                # Track wiki contributions per assignee, even when page display rows are deduplicated.
                                author_lower = current_commit['author'].lower()
                                if author_lower in assignee_lookup:
                                    matched_assignee = assignee_lookup[author_lower]
                                    recent_contributions[matched_assignee]['wiki_pages'].add(page_name)

                                if page_key not in seen_pages:
                                    seen_pages.add(page_key)
                                    action = 'Created' if status == 'A' else 'Updated'
                                    wiki_pages.append({
                                        'name': page_name,
                                        'action': action,
                                        'date': current_commit['date'],
                                        'author': current_commit['author'],
                                        'message': current_commit['message']
                                    })
            
            print('Found {:,} wiki page updates in the last {:,} days'.format(len(wiki_pages), num_day))
        else:
            print('Warning: Could not get wiki git log: {}'.format(result.stderr.decode('utf8').strip()))
            
except Exception as e:
    print('Warning: Error processing wiki updates: {}'.format(str(e)))

# Add wiki updates section
wiki_txt = '### Wiki updates (last {:,} days)\n'.format(num_day)
if wiki_pages:
    wiki_txt += 'The following wiki pages were created or updated:\n\n'

    # Sort by date (most recent first)
    wiki_pages_sorted = sorted(wiki_pages, key=lambda x: x['date'], reverse=True)
    
    for page in wiki_pages_sorted:
        wiki_page_url = repo_web_url + '/wiki/' + page['name'].replace(' ', '-')
        wiki_txt += '- **[{}]({})** - {} on {} by {}\n'.format(
            page['name'], 
            wiki_page_url,
            page['action'],
            page['date'],
            page['author']
        )
    wiki_txt += '\n'
else:
    wiki_txt += 'No wiki pages were created or updated in the last {:,} days.\n\n'.format(num_day)

issue_txt = '### Issue summary\n'
issue_txt += 'The following lists include the issues that have been inactive for more than {:,} days.\n\n'.format(since_last_updated_day)

for assignee in unique_assignees:
    assignee_key = assignee.lower()
    assigned_issues = [
        issue for issue in inactive_issues
        if any(
            isinstance(issue_assignee, str) and issue_assignee.strip().lower() == assignee_key
            for issue_assignee in issue['assignees']
        )
    ]
    assigned_issue_nums = [ issue['issue_number'] for issue in assigned_issues ]
    print('Issues assigned to {}: {}'.format(assignee, ','.join([ str(n) for n in assigned_issue_nums ])))
    assigned_open_issue_url = query_url(repo_web_url, 'assignee:{} is:open'.format(assignee))
    mentioned_unassigned_open_issue_url = query_url(repo_web_url, '-assignee:{} mentions:{} is:open'.format(assignee, assignee))
    if assigned_issues:
        issue_txt += '@{}: '.format(assignee)
        for assigned_issue in assigned_issues:
            inactive_day = int((time.time() - assigned_issue['unix_timestamp_updated']) / 86400)
            issue_txt += '{} ({} days), '.format(assigned_issue['issue_url'], inactive_day)
        issue_txt = re.sub(', $', '\n', issue_txt)
    else:
        issue_txt += '@{}: no inactive assigned issues.\n'.format(assignee)
    assignee_report_path = 'assignee_{}.txt'.format(assignee_filename_map[assignee])
    with open(assignee_report_path, 'w') as assignee_report:
        for assigned_issue in assigned_issues:
            inactive_day = int((time.time() - assigned_issue['unix_timestamp_updated']) / 86400)
            assignee_report.write('{},{},{}\n'.format(assigned_issue['issue_number'], assigned_issue['issue_url'], inactive_day))
    txt = '[List of open issues where @{} is assigned]({})\n'
    issue_txt += txt.format(assignee, assigned_open_issue_url)
    txt = '[List of open issues where @{} is not assigned but mentioned]({})\n'
    issue_txt += txt.format(assignee, mentioned_unassigned_open_issue_url)
    txt = 'Thank you for your {:,} contributions on {:,} issues, writing in {:,} wiki pages, and giving {:,} reactions in the last {:,} days!\n'
    num_wiki_pages = len(recent_contributions[assignee]['wiki_pages'])
    issue_txt += txt.format(recent_contributions[assignee]['num_comment'], recent_contributions[assignee]['num_issue'], num_wiki_pages, recent_contributions[assignee]['reactions_given'], num_day)
    #txt = 'You received {:,} reactions on your posts.\n'
    #issue_txt += txt.format(recent_contributions[assignee]['reactions_received'])
    issue_txt += '\n'

unassigned_issues = [
    issue for issue in issues
    if (not any(issue['assignees'])) and (not has_label_case_insensitive(issue['labels'], remove_label_normalized))
]
if len(unassigned_issues)==0:
    issue_txt += 'There is no unassigned issue.\n'
else:
    txt = 'There are {} unassigned issues. If anyone is willing to voluntarily take care of these, it would be very helpful: '
    issue_txt += txt.format(len(unassigned_issues))
    for unassigned_issue in unassigned_issues:
        inactive_day = int((time.time() - unassigned_issue['unix_timestamp_updated']) / 86400)
        issue_txt += '{} ({} days), '.format(unassigned_issue['issue_url'], inactive_day)
issue_txt = re.sub(', $', '\n\n', issue_txt)

with open('issue_report.txt', 'w') as f:
    f.write(wiki_txt)
    f.write(issue_txt)

print('Ending write_issue_report.py')
