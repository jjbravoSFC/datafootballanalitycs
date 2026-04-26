import re

def process_file():
    with open('app.py.bak', 'r', encoding='utf-8') as f:
        text = f.read()

    # Background colors
    bg_pattern = r"(background-color:\s*|background:\s*|backgroundColor:\s*['\"]|paper_bgcolor=['\"]|plot_bgcolor=['\"])"
    text = re.sub(bg_pattern + r"(#0f172a|#0F172A)", r"\g<1>#f0f2f5", text)
    text = re.sub(bg_pattern + r"(#1e293b|#1E293B)", r"\g<1>#ffffff", text)
    text = re.sub(bg_pattern + r"(#334155)", r"\g<1>#e2e8f0", text)

    # Border colors
    border_pattern = r"(border(?:-[a-z]+)?:\s*[^;]*?)"
    text = re.sub(border_pattern + r"(#1e293b|#1E293B)", r"\g<1>#cbd5e1", text)
    text = re.sub(border_pattern + r"(#334155)", r"\g<1>#cbd5e1", text)
    text = re.sub(border_pattern + r"(#0f172a|#0F172A)", r"\g<1>#94a3b8", text)

    # Text colors
    # Look for color: #hex or color="hex" or color='hex'
    color_pattern = r"(color:\s*['\"]?|color=['\"]|font=dict\(color=['\"]|textfont=dict\(color=['\"]|color_stripe\s*=\s*['\"])"
    text = re.sub(color_pattern + r"(#f1f5f9|#F1F5F9|white|#ffffff|#FFFFFF)", r"\g<1>#0f172a", text)
    text = re.sub(color_pattern + r"(#f8fafc|#F8FAFC)", r"\g<1>#0f172a", text)
    text = re.sub(color_pattern + r"(#e2e8f0|#E2E8F0)", r"\g<1>#1e293b", text)
    text = re.sub(color_pattern + r"(#cbd5e1|#CBD5E1)", r"\g<1>#334155", text)
    text = re.sub(color_pattern + r"(#94a3b8|#94A3B8)", r"\g<1>#475569", text)

    # Fix global app CSS block
    old_css = '''    .stApp {
        background-color: #f8f9fa; /* Light Gray/White */
        color: #0f172a; /* Dark text for light background */
    }'''
    new_css = '''    .stApp {
        background-color: #f0f2f5; /* Light Gray/White */
        color: #0f172a; /* Dark text for light background */
    }'''
    text = text.replace(old_css, new_css)
    
    # We must explicitly NOT change the actual hex representations that were meant to be dark.
    # Because we restored from app.py.bak, any dark text (like color:#0f172a) that ALREADY existed will remain dark.

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Fixed app.py from app.py.bak intelligently")

if __name__ == '__main__':
    process_file()
