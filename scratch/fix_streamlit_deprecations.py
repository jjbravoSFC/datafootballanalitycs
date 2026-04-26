import re

def fix():
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace use_container_width=True
    content = content.replace('use_container_width=True', 'width="stretch"')
    content = content.replace('use_container_width=False', 'width="content"')

    # Special case for app.py:566
    content = content.replace('col_width = "stretch" if stretch else None', 'col_width = "stretch" if stretch else "content"')
    content = content.replace('use_container_width=stretch, width=col_width', 'width=col_width')

    # Replace components.html with st.iframe
    content = re.sub(r'components\.html\(([^,]+),\s*height=([^,)]+)(?:,\s*scrolling=(?:True|False))?\)', r'st.iframe(\1, height=\2)', content)

    # Remove import streamlit.components.v1 as components
    content = re.sub(r'^\s*import streamlit\.components\.v1 as components\s*\n', '', content, flags=re.MULTILINE)

    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Done!')

if __name__ == '__main__':
    fix()
