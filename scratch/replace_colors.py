import sys

def replace_colors(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Create backups
    with open(file_path + '.bak', 'w', encoding='utf-8') as f:
        f.write(content)

    # Colors mappings (Dark to Light)
    replacements = {
        '#0f172a': '#f0f2f5', # Background (Slate 900 -> Off-white)
        '#1e293b': '#ffffff', # Cards (Slate 800 -> White)
        '#334155': '#e2e8f0', # Borders (Slate 700 -> Slate 200)
        '#475569': '#cbd5e1', # Scrollbars (Slate 600 -> Slate 300)
        '#64748b': '#94a3b8', # Muted elements (Slate 500 -> Slate 400)
        
        '#f1f5f9': '#0f172a', # Main text (Slate 100 -> Slate 900)
        '#f8fafc': '#0f172a', # Header text (Slate 50 -> Slate 900)
        '#e2e8f0': '#1e293b', # Secondary text (Slate 200 -> Slate 800)
        '#cbd5e1': '#334155', # Muted text (Slate 300 -> Slate 700)
        '#94a3b8': '#475569', # Muted text (Slate 400 -> Slate 600)
        
        'color: white;': 'color: #0f172a;',
        'color:white;': 'color:#0f172a;',
        'color: white': 'color: #0f172a',
        'color:white': 'color:#0f172a',
        "'white'": "'#0f172a'",
        '"white"': '"#0f172a"'
    }

    # Apply replacements
    for dark, light in replacements.items():
        content = content.replace(dark, light)
        content = content.replace(dark.upper(), light)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print('Colors replaced in', file_path)

if __name__ == '__main__':
    replace_colors('app.py')
