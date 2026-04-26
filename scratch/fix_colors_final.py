import re

def process_file():
    with open('app.py.bak', 'r', encoding='utf-8') as f:
        text = f.read()

    # Background colors
    bg_pattern = r"(background(?:-color)?:\s*|backgroundColor:\s*['\"]|paper_bgcolor=['\"]|plot_bgcolor=['\"])"
    text = re.sub(bg_pattern + r"(#0f172a|#0F172A)", r"\g<1>#ffffff", text)
    text = re.sub(bg_pattern + r"(#1e293b|#1E293B)", r"\g<1>#f0f2f5", text)
    text = re.sub(bg_pattern + r"(#334155)", r"\g<1>#e2e8f0", text)

    # Border colors
    border_pattern = r"(border(?:-[a-z]+)?:\s*[^;]*?)"
    text = re.sub(border_pattern + r"(#1e293b|#1E293B)", r"\g<1>#cbd5e1", text)
    text = re.sub(border_pattern + r"(#334155)", r"\g<1>#cbd5e1", text)
    text = re.sub(border_pattern + r"(#0f172a|#0F172A)", r"\g<1>#e2e8f0", text)

    # Text colors
    color_pattern = r"((?<!-)\bcolor:\s*['\"]?|\bcolor=['\"]|font=dict\(color=['\"]|textfont=dict\(color=['\"]|color_stripe\s*=\s*['\"])"
    text = re.sub(color_pattern + r"(#f1f5f9|#F1F5F9|white|#ffffff|#FFFFFF)", r"\g<1>#0f172a", text)
    text = re.sub(color_pattern + r"(#f8fafc|#F8FAFC)", r"\g<1>#0f172a", text)
    text = re.sub(color_pattern + r"(#e2e8f0|#E2E8F0)", r"\g<1>#1e293b", text)
    text = re.sub(color_pattern + r"(#cbd5e1|#CBD5E1)", r"\g<1>#334155", text)
    text = re.sub(color_pattern + r"(#94a3b8|#94A3B8)", r"\g<1>#475569", text)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("Cleaned up backgrounds perfectly")

if __name__ == '__main__':
    process_file()
