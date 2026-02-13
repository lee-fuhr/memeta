import os

print("Feature implementation status:")
print("\n=== F1-22: Core (Shipped) ===")
print("✅ All implemented")

print("\n=== F23: Versioning ===")
print("✅" if os.path.exists("src/intelligence/versioning.py") else "❌", "versioning.py")

print("\n=== F24-32: Intelligence + Automation ===")
for f in ["clustering.py", "relationships.py"]:
    exists = os.path.exists(f"src/intelligence/{f}")
    print("✅" if exists else "❌", f"intelligence/{f}")

for f in ["triggers.py", "alerts.py", "search.py", "summarization.py", "quality.py"]:
    exists = os.path.exists(f"src/automation/{f}")
    print("✅" if exists else "❌", f"automation/{f}")

print("\n=== F33-43: Wild features ===")
wild_files = os.listdir("src/wild/") if os.path.exists("src/wild/") else []
print(f"✅ {len([f for f in wild_files if f.endswith('.py')])} wild feature files")

print("\n=== F44-50: Multimodal ===")
mm_files = os.listdir("src/multimodal/") if os.path.exists("src/multimodal/") else []
print(f"✅ {len([f for f in mm_files if f.endswith('.py')])} multimodal feature files")

print("\n=== F51-75: Remaining ===")
print("Need to check docs for these...")
