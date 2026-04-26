import sys
import os

# Add the directory to sys.path so we can import app
sys.path.insert(0, r"c:\OneDrive\OneDrive\Desarrollos Locales\Temporadas Clasificaciones")

from app import get_referees_list, get_referee_stats, get_h2h_matches, get_historical_standings, get_top_players, get_shooting_profile

print("Testing get_referees_list...")
refs = get_referees_list()
print(f"Found {len(refs)} referees. First 5: {refs[:5]}")

print("\nTesting get_referee_stats...")
if refs:
    ref = refs[0]
    stats = get_referee_stats(ref)
    print(f"Stats for {ref}: {stats}")

print("\nTesting get_h2h_matches...")
h2h = get_h2h_matches("Barcelona", "Real Madrid")
print("H2H Barça vs Madrid:")
for m in h2h:
    print(f"  {m}")

print("\nTesting get_historical_standings...")
standings_b = get_historical_standings("Barcelona")
standings_m = get_historical_standings("Real Madrid")
print(f"Barcelona: {standings_b}")
print(f"Real Madrid: {standings_m}")

print("\nTesting get_top_players for 2025-2026...")
top_b = get_top_players("2025-2026", "Barcelona")
top_m = get_top_players("2025-2026", "Real Madrid")
print(f"Barcelona Top Players: {top_b}")
print(f"Real Madrid Top Players: {top_m}")

print("\nTesting get_shooting_profile for 2025-2026...")
print("Barcelona Profile:")
sit, bod = get_shooting_profile("2025-2026", "Barcelona")
print(f"  Sit: {sit} | Body: {bod}")
print("Real Madrid Profile:")
sit, bod = get_shooting_profile("2025-2026", "Real Madrid")
print(f"  Sit: {sit} | Body: {bod}")

print("\nAll tests ran.")
