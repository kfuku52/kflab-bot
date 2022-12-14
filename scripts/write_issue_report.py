import re
import sys
import time

print('Starting write_issue_report.py')

hub_out_file = sys.argv[1]
since_last_updated_day = int(sys.argv[2])
remove_label = sys.argv[3]
repo_url = sys.argv[4]

since_last_updated_sec = since_last_updated_day * 86400

with open(hub_out_file, 'r') as f:
    hub_txt = f.read()

hub_items = hub_txt.split('\n')
if hub_items[len(hub_items)-1]=='':
    hub_items = hub_items[0:(len(hub_items)-1)]

num_item = 7
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

inactive_issues = [ issue for issue in issues if (time.time()-issue['unix_timestamp_updated']) > since_last_updated_sec ]
inactive_issues = [ issue for issue in inactive_issues if remove_label not in issue['labels'] ]
print('Number of inactive Issues: {:,}'.format(len(inactive_issues)))

unique_assignees = list(set([ assignee.replace(' ', '') for issue in inactive_issues for assignee in issue['assignees'] if assignee!='' ]))
print('Number of assignees in inactive Issues: {:,}'.format(len(unique_assignees)))
unique_assignee_txt = ','.join(unique_assignees)
f = open('unique_assignees.txt', 'w')
f.write(unique_assignee_txt)
f.close()

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
    issue_txt = re.sub(', $', '\n', issue_txt)
    txt = '[List of open issues where @{} is assigned]({})\n'
    issue_txt += txt.format(assignee, assigned_open_issue_url)
    txt = '[List of open issues where @{} is not assigned but mentioned]({})\n'
    issue_txt += txt.format(assignee, mentioned_unassigned_open_issue_url)
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
f.write(issue_txt)
f.close()

print('Ending write_issue_report.py')