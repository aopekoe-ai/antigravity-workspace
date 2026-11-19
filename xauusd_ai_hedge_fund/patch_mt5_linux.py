import os

for p in ['/tmp/config.sh', '/tmp/mt5.sh']:
    if os.path.exists(p):
        with open(p, 'r') as f:
            s = f.read()
        s = s.replace('test $FIRST_RUN || return', '[ -n "$FIRST_RUN" ] || return 0')
        with open(p, 'w') as f:
            f.write(s)
        print(f"Patched {p}")
