import sys
import time

print('Starting write_email_text.py')

hub_out_file = sys.argv[1]
since_last_updated_sec = int(sys.argv[2])

with open(hub_out_file, 'r') as f:
    hub_txt = f.read()

hub_items = hub_txt.split('\n')
if hub_items[len(hub_items)-1]=='':
    hub_items = hub_items[0:(len(hub_items)-1)]

num_open_issue = int(len(hub_items)/6)
print('Number of open Issues: {:,}'.format(num_open_issue))

issues = list()
for i in range(num_open_issue):
    issues.append(dict())
    issues[i]['issue_number'] = int(hub_items[i*6+0])
    issues[i]['assignees'] = hub_items[i*6+1].split(',')
    issues[i]['relative_time_updated'] = hub_items[i*6+2]
    issues[i]['unix_timestamp_updated'] = int(hub_items[i*6+3])
    issues[i]['issue_title'] = hub_items[i*6+4]
    issues[i]['issue_url'] = hub_items[i*6+5]

inactive_issues = [ issue for issue in issues if (time.time()-issue['unix_timestamp_updated']) > since_last_updated_sec ]
print('Number of inactive Issues: {:,}'.format(len(inactive_issues)))

unique_assignees = list(set([ assignee for issue in inactive_issues for assignee in issue['assignees'] if assignee!='' ]))
print('Number of assignees in inactive Issues: {:,}'.format(len(unique_assignees)))
for assignee in unique_assignees:
    assigned_issues = [ issue for issue in inactive_issues if assignee in issue['assignees'] ]
    assigned_issue_nums = [ issue['issue_number'] for issue in assigned_issues ]
    print('Issues assigned to {}: {}'.format(assignee, ','.join([ str(n) for n in assigned_issue_nums ])))
    assignee_txt = ''
    for assigned_issue in assigned_issues:
        inactive_day = int((time.time() - assigned_issue['unix_timestamp_updated']) / 86400)
        assignee_txt += 'Title: {}\n'.format(assigned_issue['issue_title'])
        assignee_txt += 'This issue has been inactive for {:,} days. '.format(inactive_day)
        assignee_txt += 'As the assignee, you ({}) are expected to post an update.\n'.format(assignee)
        assignee_txt += assigned_issue['issue_url']+'\n\n'
    #print(assignee_txt)
    assignee_file = 'assignee_{}.txt'.format(assignee)
    f = open(assignee_file, 'w')
    f.write(assignee_txt)
    f.close()

print('Ending write_email_text.py')