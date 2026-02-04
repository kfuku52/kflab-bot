import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time
from distutils.util import strtobool

print('Starting write_issue_report.py')

hub_out_file = sys.argv[1]
since_last_updated_day = int(sys.argv[2])
remove_label = sys.argv[3]
generate_issue_hyperlink = strtobool(sys.argv[4])
repo_url = sys.argv[5]

since_last_updated_sec = since_last_updated_day * 86400

with open(hub_out_file, 'r') as f:
    hub_txt = f.read()

hub_items = hub_txt.split('\n')
if hub_items[len(hub_items)-1]=='':
    hub_items = hub_items[0:(len(hub_items)-1)]

num_item = 8
num_open_issue = int(len(hub_items)/num_item)
print('Number of open Issues: {:,}'.format(num_open_issue))

issues = list()
for i in range(num_open_issue):
    issues.append(dict())
    issues[i]['issue_number'] = int(hub_items[i*num_item+0])
    issues[i]['assignees'] = hub_items[i*num_item+1].split(', ')
    issues[i]['relative_time_updated'] = hub_items[i*num_item+2]
    issues[i]['unix_timestamp_updated'] = int(hub_items[i*num_item+3])
    issues[i]['issue_title'] = hub_items[i*num_item+4]
    issues[i]['issue_url'] = hub_items[i*num_item+5]
    issues[i]['labels'] = hub_items[i*num_item+6].split(', ')
if not generate_issue_hyperlink:
    print('Issue hyperlinks will not be generated.')
    for i in range(len(issues)):
        # https://github.com/hackmdio/hackmd-io-issues/issues/261
        issues[i]['issue_url'] = re.sub('.*/', '#<span/>', issues[i]['issue_url'])

inactive_issues = [ issue for issue in issues if (time.time()-issue['unix_timestamp_updated']) > since_last_updated_sec ]
inactive_issues = [ issue for issue in inactive_issues if remove_label not in issue['labels'] ]
print('Number of inactive Issues: {:,}'.format(len(inactive_issues)))

unique_assignees = sorted(set([ assignee.replace(' ', '') for issue in inactive_issues for assignee in issue['assignees'] if assignee!='' ]))
print('Number of assignees in inactive Issues: {:,}'.format(len(unique_assignees)))
unique_assignee_txt = ','.join(unique_assignees)
f = open('unique_assignees.txt', 'w')
f.write(unique_assignee_txt + '\n')
f.close()

# Clean up stale per-assignee summaries before writing fresh ones
for assignee_file in glob.glob('assignee_*.txt'):
    try:
        os.remove(assignee_file)
    except OSError as exc:
        print('Failed to remove {}: {}'.format(assignee_file, exc))

# Member-wise contributions in the last X days
num_day = 7
today = datetime.datetime.today()
today_str = today.strftime('%Y-%m-%d')
startday = datetime.datetime.now() - datetime.timedelta(days=num_day)
startday_str = startday.strftime('%Y-%m-%d')
gh_command1 = ['gh', 'issue', 'list', '--limit', str(1000), '--state', 'all', '--search', 'updated:{}..{}'.format(startday_str, today_str)]
gh_command1_str = ' '.join(gh_command1)
print('gh command: {}'.format(gh_command1_str))
gh_out1 = subprocess.run(gh_command1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
recent_issue_nums = re.sub('\t.*', '', gh_out1.stdout.decode('utf8')).split('\n')
recent_issue_nums = sorted([ int(rin) for rin in recent_issue_nums if rin!='' ])
print('Issues updated in the last {:,} days: {}'.format(num_day, ', '.join([ str(r) for r in recent_issue_nums ])))
time_pattern = '%Y-%m-%dT%H:%M:%SZ'
recent_contributions = dict()
# Create case-insensitive lookup map for matching wiki authors and reactors
assignee_lookup = {assignee.lower(): assignee for assignee in unique_assignees}
for assignee in unique_assignees:
    recent_contributions[assignee] = dict()
    recent_contributions[assignee]['issue_numbers'] = list()
    recent_contributions[assignee]['timestamps'] = list()
    recent_contributions[assignee]['wiki_pages'] = set()
    recent_contributions[assignee]['reactions_given'] = 0
    recent_contributions[assignee]['reactions_received'] = 0
for issue_num in recent_issue_nums:
    gh_command2 = ['gh', 'issue', 'view', str(issue_num), '--json', 'assignees,author,body,closed,closedAt,comments,createdAt,id,labels,milestone,number,reactionGroups,state,title,updatedAt,url']
    gh_command2_str = ' '.join(gh_command2)
    gh_out2 = subprocess.run(gh_command2_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if gh_out2.returncode != 0:
        print('gh command failed (issue {}): {}'.format(issue_num, gh_out2.stderr.decode('utf8').strip()))
        continue
    issue = json.loads(gh_out2.stdout.decode('utf8'))
    issue_created_at = datetime.datetime.strptime(issue['createdAt'], time_pattern)
    issue_author = issue['author']['login']
    if (issue_created_at > startday)&(issue_author in recent_contributions.keys()):
        recent_contributions[issue_author]['issue_numbers'].append(issue_num)
        recent_contributions[issue_author]['timestamps'].append(issue_created_at)
    
    # Track reactions on the issue itself
    if 'reactionGroups' in issue and issue['reactionGroups']:
        # Get detailed reaction info to see who reacted
        gh_command_reactions = ['gh', 'api', 'repos/{}/issues/{}/reactions'.format(repo_url.replace('https://github.com/', ''), issue_num), '--paginate', '--jq', '.[]']
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
                reaction_created_at = datetime.datetime.strptime(reaction['created_at'], time_pattern)
                reactor = reaction['user']['login']
                if reaction_created_at > startday:
                    # Count reactions given
                    if reactor in recent_contributions.keys():
                        recent_contributions[reactor]['reactions_given'] += 1
                    # Count reactions received by issue author
                    if issue_author in recent_contributions.keys():
                        recent_contributions[issue_author]['reactions_received'] += 1
    
    for comment in issue['comments']:
        comment_created_at = datetime.datetime.strptime(comment['createdAt'], time_pattern)
        comment_author = comment['author']['login']
        if (comment_created_at > startday)&(comment_author in recent_contributions.keys()):
            recent_contributions[comment_author]['issue_numbers'].append(issue_num)
            recent_contributions[comment_author]['timestamps'].append(comment_created_at)
        
        # Track reactions on comments
        if 'reactions' in comment and comment['reactions']:
            comment_id = comment['id']
            # Note: comment reactions are included in the issue view JSON, but we need to check if they have the detailed user info
            # The reactionGroups in comments may not have user details, so we'll need to make an API call
            gh_command_comment_reactions = ['gh', 'api', 'repos/{}/issues/comments/{}/reactions'.format(repo_url.replace('https://github.com/', ''), comment_id), '--paginate', '--jq', '.[]']
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
                    reaction_created_at = datetime.datetime.strptime(reaction['created_at'], time_pattern)
                    reactor = reaction['user']['login']
                    if reaction_created_at > startday:
                        # Count reactions given
                        if reactor in recent_contributions.keys():
                            recent_contributions[reactor]['reactions_given'] += 1
                        # Count reactions received by comment author
                        if comment_author in recent_contributions.keys():
                            recent_contributions[comment_author]['reactions_received'] += 1
for assignee in unique_assignees:
    recent_contributions[assignee]['num_issue'] = len(set(recent_contributions[assignee]['issue_numbers']))
    recent_contributions[assignee]['num_comment'] = len(recent_contributions[assignee]['issue_numbers'])

# Get Wiki updates from the last week
wiki_pages = []
try:
    # Clone or update the wiki repository
    wiki_dir = 'wiki_temp'
    wiki_url = repo_url + '.wiki.git'
    
    if os.path.exists(wiki_dir):
        # Update existing wiki clone
        print('Updating existing wiki repository...')
        subprocess.run(['git', '-C', wiki_dir, 'pull'], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        # Clone the wiki repository
        print('Cloning wiki repository from {}...'.format(wiki_url))
        result = subprocess.run(['git', 'clone', wiki_url, wiki_dir], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print('Warning: Could not clone wiki repository: {}'.format(result.stderr.decode('utf8').strip()))
    
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
                if '|' in line:
                    # This is a commit line
                    parts = line.split('|')
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
                        filename = parts[1]
                        
                        # Convert filename to wiki page name (remove .md extension)
                        if filename.endswith('.md'):
                            page_name = filename[:-3].replace('-', ' ')
                            page_key = (page_name, current_commit['date'])
                            
                            if page_key not in seen_pages and status in ['A', 'M']:
                                seen_pages.add(page_key)
                                action = 'Created' if status == 'A' else 'Updated'
                                wiki_pages.append({
                                    'name': page_name,
                                    'action': action,
                                    'date': current_commit['date'],
                                    'author': current_commit['author'],
                                    'message': current_commit['message']
                                })
                                
                                # Track wiki contributions per assignee (case-insensitive matching)
                                author_lower = current_commit['author'].lower()
                                if author_lower in assignee_lookup:
                                    matched_assignee = assignee_lookup[author_lower]
                                    recent_contributions[matched_assignee]['wiki_pages'].add(page_name)
            
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
        wiki_page_url = repo_url + '/wiki/' + page['name'].replace(' ', '-')
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
    assigned_issues = [ issue for issue in inactive_issues if assignee in issue['assignees'] ]
    assigned_issue_nums = [ issue['issue_number'] for issue in assigned_issues ]
    print('Issues assigned to {}: {}'.format(assignee, ','.join([ str(n) for n in assigned_issue_nums ])))
    assigned_open_issue_url = repo_url+'/issues?q=assignee%3A'+assignee+'+is%3Aopen'
    mentioned_unassigned_open_issue_url = repo_url+'/issues?q=-assignee%3A'+assignee+'+mentions%3A'+assignee+'+is%3Aopen'
    issue_txt += '@{}: '.format(assignee)
    for assigned_issue in assigned_issues:
        inactive_day = int((time.time() - assigned_issue['unix_timestamp_updated']) / 86400)
        issue_txt += '{} ({} days), '.format(assigned_issue['issue_url'], inactive_day)
    assignee_report_path = 'assignee_{}.txt'.format(assignee)
    with open(assignee_report_path, 'w') as assignee_report:
        for assigned_issue in assigned_issues:
            inactive_day = int((time.time() - assigned_issue['unix_timestamp_updated']) / 86400)
            assignee_report.write('{},{},{}\n'.format(assigned_issue['issue_number'], assigned_issue['issue_url'], inactive_day))
    issue_txt = re.sub(', $', '\n', issue_txt)
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

unassigned_issues = [ issue for issue in issues if issue['assignees'][0]=='' ]
if len(unassigned_issues)==0:
    issue_txt += 'There is no unassigned issue.\n'
else:
    txt = 'There are {} unassigned issues. If anyone is willing to voluntarily take care of these, it would be very helpful: '
    issue_txt += txt.format(len(unassigned_issues))
    for unassigned_issue in unassigned_issues:
        inactive_day = int((time.time() - unassigned_issue['unix_timestamp_updated']) / 86400)
        issue_txt += '{} ({} days), '.format(unassigned_issue['issue_url'], inactive_day)
issue_txt = re.sub(', $', '\n\n', issue_txt)

f = open('issue_report.txt', 'w')
f.write(wiki_txt)
f.write(issue_txt)
f.close()

print('Ending write_issue_report.py')