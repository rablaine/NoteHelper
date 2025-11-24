#!/usr/bin/env python3
"""Add 'g' to Flask imports in route files."""

import os
import re

def add_g_to_imports(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if file uses g.user
    if 'g.user' not in content:
        return False
    
    # Check if g is already imported
    if re.search(r'\bfrom flask import.*\bg\b', content):
        return False
    
    # Add g to flask imports
    pattern = r'(from flask import [^\n]+)'
    match = re.search(pattern, content)
    
    if match:
        old_import = match.group(1)
        new_import = old_import.rstrip() + ', g'
        content = content.replace(old_import, new_import, 1)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Updated: {filepath}")
        return True
    
    return False

def main():
    count = 0
    for filename in os.listdir('app/routes'):
        if filename.endswith('.py'):
            filepath = os.path.join('app/routes', filename)
            if add_g_to_imports(filepath):
                count += 1
    
    print(f"\nTotal files updated: {count}")

if __name__ == '__main__':
    main()
