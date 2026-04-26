import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the CSS block that was accidentally converted to light color text on light background
old_css = """    /* Global Text Color for Main App (override general text) */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp p, .stApp span, .stApp div, .stApp li {
        color: #f0f2f5;
    }"""

new_css = """    /* Global Text Color for Main App (override general text) */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp p, .stApp span, .stApp div, .stApp li {
        color: #0f172a;
    }"""

content = content.replace(old_css, new_css)

old_css2 = """    .stApp {
        background-color: #f8f9fa; /* Light Gray/White */
        color: #f0f2f5; /* Dark text for light background */
    }"""

new_css2 = """    .stApp {
        background-color: #f0f2f5; /* Light Gray/White */
        color: #0f172a; /* Dark text for light background */
    }"""

content = content.replace(old_css2, new_css2)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed CSS in app.py')
