import codecs
import re

filepath = r"c:\OneDrive\OneDrive\Desarrollos Locales\Temporadas Clasificaciones\app.py"

with codecs.open(filepath, 'r', 'utf-8') as f:
    code = f.read()

# Bulk replace use_container_width=True logic
code = re.sub(r'use_container_width\s*=\s*True', 'width="stretch"', code)
code = re.sub(r'use_container_width\s*=\s*False', 'width="content"', code)

with codecs.open(filepath, 'w', 'utf-8') as f:
    f.write(code)

print("Replacement of use_container_width complete.")
