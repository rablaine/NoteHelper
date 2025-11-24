#!/usr/bin/env python3
"""
Script to help identify all user_id references that need to be removed
for single-user mode conversion.
"""

import os
import re

def scan_file(filepath):
    """Scan a Python file for user-related patterns."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    patterns = {
        'login_required': r'@login_required',
        'current_user': r'current_user',
        'user_id_filter': r'filter_by\(user_id=',
        'user_id_param': r'user_id=current_user\.id',
        'is_admin_check': r'current_user\.is_admin',
    }
    
    matches = []
    for line_num, line in enumerate(lines, 1):
        for pattern_name, pattern in patterns.items():
            if re.search(pattern, line):
                matches.append({
                    'file': filepath,
                    'line': line_num,
                    'type': pattern_name,
                    'content': line.strip()
                })
    
    return matches

def main():
    """Scan all Python files in app/ directory."""
    all_matches = []
    
    for root, dirs, files in os.walk('app'):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                matches = scan_file(filepath)
                all_matches.extend(matches)
    
    # Group by type
    by_type = {}
    for match in all_matches:
        match_type = match['type']
        if match_type not in by_type:
            by_type[match_type] = []
        by_type[match_type].append(match)
    
    # Print report
    print(f"Total matches found: {len(all_matches)}\n")
    
    for match_type, matches in sorted(by_type.items()):
        print(f"\n{match_type.upper()} ({len(matches)} matches):")
        print("=" * 80)
        for match in matches[:10]:  # Show first 10
            print(f"  {match['file']}:{match['line']}")
            print(f"    {match['content']}")
        if len(matches) > 10:
            print(f"  ... and {len(matches) - 10} more")

if __name__ == '__main__':
    main()
