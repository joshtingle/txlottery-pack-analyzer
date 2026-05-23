import json

with open('tx_lottery_latest.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

with open('tx-lottery-analyzer.jsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

db_start = next(i for i, l in enumerate(lines) if l.strip().startswith('const DB ='))
component_lines = lines[db_start + 1:]

db_json = json.dumps(db, separators=(',', ':'))
db_line = 'const DB = ' + db_json + ';\n'

new_jsx = [lines[0]] + [db_line] + component_lines

with open('tx-lottery-analyzer.jsx', 'w', encoding='utf-8') as f:
    f.writelines(new_jsx)

print('Done.')
print('DB line chars:', len(db_line))
print('Total lines:', len(new_jsx))
print('Games:', db['gameCount'], ' score_max:', db['score_max'], ' asOf:', db['asOf'])
