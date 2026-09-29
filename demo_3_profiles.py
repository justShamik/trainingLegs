import os
from app.data.db import init_db
from app.data.queries import save_user_profile
from app.engine.planner import TrainingPlanner

db_path = "demo_plan.db"
if os.path.exists(db_path):
    os.remove(db_path)
init_db(db_path)

# 1. 10K Profile
save_user_profile({'race_distance_type': '10K', 'target_time_str': '0:42:00', 'race_date': '2026-10-30'}, db_path=db_path)
p10k = TrainingPlanner(db_path=db_path).generate_plan()
print("=== 10K ROAD GOAL PLAN ===")
print("Methodology:", p10k["methodology_name"])
print("Volume:", p10k["total_volume_km"], "km")
for s in p10k["sessions"]:
    print(f"  {s['day_of_week']}: {s['session_type']} ({s['distance_km']}km / {s['duration_min']}min) -> {s['target_pace_or_hr']}")

# 2. Marathon Profile
save_user_profile({'race_distance_type': 'Marathon', 'target_time_str': '3:30:00', 'race_date': '2026-11-15'}, db_path=db_path)
pmara = TrainingPlanner(db_path=db_path).generate_plan()
print("\n=== MARATHON ROAD GOAL PLAN ===")
print("Methodology:", pmara["methodology_name"])
print("Volume:", pmara["total_volume_km"], "km")
for s in pmara["sessions"]:
    print(f"  {s['day_of_week']}: {s['session_type']} ({s['distance_km']}km / {s['duration_min']}min) -> {s['target_pace_or_hr']}")

# 3. 50K Ultra Profile
save_user_profile({'race_distance_type': '50K Ultra', 'target_time_str': '5:45:00', 'race_date': '2026-12-10'}, db_path=db_path)
pultra = TrainingPlanner(db_path=db_path).generate_plan()
print("\n=== 50K ULTRA TRAIL GOAL PLAN ===")
print("Methodology:", pultra["methodology_name"])
print("Volume:", pultra["total_volume_km"], "km")
for s in pultra["sessions"]:
    print(f"  {s['day_of_week']}: {s['session_type']} ({s['distance_km']}km / {s['duration_min']}min) -> {s['target_pace_or_hr']}")

if os.path.exists(db_path):
    os.remove(db_path)
