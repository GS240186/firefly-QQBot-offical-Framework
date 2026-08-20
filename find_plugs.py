with open(r'd:\小流萤bot\console_server.py','r',encoding='utf-8') as f:
    t = f.read()
import re
for m in re.finditer(r'def set_feature_enabled_global|def is_feature_enabled|set_feature_enabled\b', t):
    s = m.start()
    print(s, '->', t[max(0,s-80):s+200].replace('\n', ' | '))
    print('---')
