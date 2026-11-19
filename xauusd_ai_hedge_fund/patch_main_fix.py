with open("/tmp/main.sh", "r") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "MT5_SETUP_PID=$!" in line:
        lines[i-1] = "wait_for_mt5_and_type_server &\n"
with open("/tmp/main.sh", "w") as f:
    f.writelines(lines)
print("Line 36 restored")
