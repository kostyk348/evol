"""Тест hot reload + checkpoint + time."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from repl import SimState

s = SimState()
s.dt = 0.1

# 1. Hot reload test
with open("_hot_test.evol", "w", encoding="utf-8") as f:
    f.write('lib hot { rule r = when boot => { x := 1 } }')

s.load_file("_hot_test.evol")
s.emit_msg("boot")
print(s.step(1))
print("Store v1:", s.sigma)

time.sleep(0.1)
with open("_hot_test.evol", "w", encoding="utf-8") as f:
    f.write('lib hot { rule r = when boot => { x := 42 } }')

result = s.check_watch()
for r in result:
    print(r)

s.emit_msg("boot")
print(s.step(1))
print("Store v2:", s.sigma)

# 2. Time test
print("Time:", s.time, "dt:", s.dt)
s.dt = 0.5
s.emit_msg("boot")
s.step(1)
print("Time after step:", s.time)

# 3. Checkpoint round-trip
print(s.checkpoint("_test_cp.json"))
s2 = SimState()
print(s2.restore("_test_cp.json"))
print("Restored store:", s2.sigma)
print("Restored time:", s2.time)

os.remove("_hot_test.evol")
os.remove("_test_cp.json")
print("\nALL REPL TESTS OK")
