#!/usr/bin/env python3
"""Manual update to add connection pooling to fsrs_scheduler.py"""

# Read original file
with open('fsrs_scheduler.py', 'r') as f:
    lines = f.readlines()

# Output lines
output = []

i = 0
while i < len(lines):
    line = lines[i]
    
    # Add import after other imports
    if i == 16 and line.strip() == "":
        output.append("\nimport sys\n")
        output.append("from pathlib import Path as _Path\n")
        output.append("sys.path.insert(0, str(_Path(__file__).parent))\n")
        output.append("from db_pool import get_connection\n")
        output.append("\n")
        i += 1
        continue
    
    # Skip _connect method entirely (lines 84-88)
    if "_connect(self)" in line:
        # Skip until we hit the next method
        while i < len(lines) and not lines[i].strip().startswith("def _init_db"):
            i += 1
        continue
    
    # Replace _init_db method
    if "def _init_db(self):" in line:
        output.append(line)  # def _init_db...
        output.append(lines[i+1])  # docstring
        i += 2
        
        # Add connection context manager
        output.append("        with get_connection(self.db_path) as conn:\n")
        
        # Process body until conn.close()
        while i < len(lines):
            if "conn.close()" in lines[i]:
                i += 1
                break
            
            # Indent existing lines by 4 more spaces (within context manager)
            body_line = lines[i]
            if body_line.strip():  # Non-empty
                output.append("    " + body_line)
            else:
                output.append(body_line)
            i += 1
        continue
    
    # Replace other _connect() calls
    if "conn = self._connect()" in line:
        indent = len(line) - len(line.lstrip())
        output.append(" " * indent + "with get_connection(self.db_path) as conn:\n")
        i += 1
        
        # Indent body until conn.close()
        while i < len(lines):
            if "conn.close()" in lines[i]:
                i += 1
                break
            
            body_line = lines[i]
            if body_line.strip():
                output.append("    " + body_line)
            else:
                output.append(body_line)
            i += 1
        continue
    
    # Default: keep line as-is
    output.append(line)
    i += 1

# Write output
with open('fsrs_scheduler.py', 'w') as f:
    f.writelines(output)

print("✅ Updated fsrs_scheduler.py")
