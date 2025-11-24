#!/usr/bin/env python3
"""
Automated conversion script to remove multi-user authentication and convert to single-user mode.
This script performs bulk find/replace operations across the codebase.
"""

import os
import re
from pathlib import Path

class SingleUserConverter:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.changes = []
        
    def log_change(self, filepath, line_num, old_line, new_line, change_type):
        """Log a change for reporting."""
        self.changes.append({
            'file': filepath,
            'line': line_num,
            'old': old_line,
            'new': new_line,
            'type': change_type
        })
    
    def remove_login_required_decorator(self, filepath):
        """Remove @login_required decorators and associated imports."""
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        skip_next_blank = False
        changes_made = 0
        
        for i, line in enumerate(lines):
            # Skip @login_required decorator
            if '@login_required' in line and line.strip() == '@login_required':
                self.log_change(filepath, i+1, line.rstrip(), '[REMOVED]', 'decorator')
                skip_next_blank = True
                changes_made += 1
                continue
            
            # Remove login_required from imports
            if 'from flask_login import' in line and 'login_required' in line:
                # Remove login_required from the import
                new_line = re.sub(r',?\s*login_required\s*,?', '', line)
                # Clean up any double commas or trailing commas
                new_line = re.sub(r',\s*,', ',', new_line)
                new_line = re.sub(r'import\s*,', 'import', new_line)
                new_line = re.sub(r',\s*\)', ')', new_line)
                
                # If import is now empty, skip the line
                if 'import  ' in new_line or 'import )' in new_line or new_line.strip().endswith('import'):
                    self.log_change(filepath, i+1, line.rstrip(), '[REMOVED - empty import]', 'import')
                    changes_made += 1
                    continue
                
                if new_line != line:
                    self.log_change(filepath, i+1, line.rstrip(), new_line.rstrip(), 'import')
                    new_lines.append(new_line)
                    changes_made += 1
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        if changes_made > 0 and not self.dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        
        return changes_made
    
    def remove_user_id_filters(self, filepath):
        """Remove .filter_by(user_id=current_user.id) from queries."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        changes_made = 0
        
        # Pattern 1: .filter_by(user_id=current_user.id) as only filter
        pattern1 = r'\.filter_by\(user_id=current_user\.id\)'
        matches1 = re.finditer(pattern1, content)
        for match in matches1:
            changes_made += 1
        content = re.sub(pattern1, '', content)
        
        # Pattern 2: .filter_by(user_id=current_user.id, other_field=value)
        pattern2 = r'\.filter_by\(user_id=current_user\.id,\s*'
        content = re.sub(pattern2, '.filter_by(', content)
        
        # Pattern 3: .filter_by(other_field=value, user_id=current_user.id)
        pattern3 = r',\s*user_id=current_user\.id\)'
        content = re.sub(pattern3, ')', content)
        
        if content != original_content and not self.dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        
        return changes_made if content != original_content else 0
    
    def remove_admin_checks(self, filepath):
        """Remove is_admin checks and their associated blocks."""
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        new_lines = []
        skip_until_dedent = False
        indent_level = 0
        changes_made = 0
        
        for i, line in enumerate(lines):
            # Check for admin check pattern
            if 'if not current_user.is_admin:' in line:
                skip_until_dedent = True
                indent_level = len(line) - len(line.lstrip())
                self.log_change(filepath, i+1, line.rstrip(), '[REMOVED - admin check block]', 'admin_check')
                changes_made += 1
                continue
            
            # Skip lines in the admin check block
            if skip_until_dedent:
                current_indent = len(line) - len(line.lstrip())
                # Stop skipping when we dedent or hit another statement at same level
                if current_indent <= indent_level and line.strip():
                    skip_until_dedent = False
                    new_lines.append(line)
                else:
                    continue
            else:
                new_lines.append(line)
        
        if changes_made > 0 and not self.dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        
        return changes_made
    
    def replace_current_user_id(self, filepath):
        """Replace current_user.id with get_single_user().id in object creation."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # For now, just remove user_id= parameters in object creation
        # Pattern: user_id=current_user.id in function calls/constructors
        pattern = r',?\s*user_id=current_user\.id\s*,?'
        
        def cleanup_commas(text):
            # Fix double commas
            text = re.sub(r',\s*,', ',', text)
            # Fix trailing comma before closing paren
            text = re.sub(r',\s*\)', ')', text)
            # Fix comma after opening paren
            text = re.sub(r'\(\s*,', '(', text)
            return text
        
        content = re.sub(pattern, '', content)
        content = cleanup_commas(content)
        
        if content != original_content and not self.dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        
        return 1 if content != original_content else 0
    
    def process_file(self, filepath):
        """Process a single Python file."""
        if not filepath.endswith('.py'):
            return
        
        print(f"Processing: {filepath}")
        
        changes = 0
        changes += self.remove_login_required_decorator(filepath)
        changes += self.remove_user_id_filters(filepath)
        changes += self.remove_admin_checks(filepath)
        changes += self.replace_current_user_id(filepath)
        
        if changes > 0:
            print(f"  ✓ {changes} changes made")
    
    def process_directory(self, directory='app/routes'):
        """Process all Python files in a directory."""
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    self.process_file(filepath)
    
    def generate_report(self):
        """Generate a summary report of all changes."""
        print("\n" + "="*80)
        print("CONVERSION SUMMARY")
        print("="*80)
        
        by_type = {}
        for change in self.changes:
            change_type = change['type']
            if change_type not in by_type:
                by_type[change_type] = []
            by_type[change_type].append(change)
        
        for change_type, changes in sorted(by_type.items()):
            print(f"\n{change_type.upper()}: {len(changes)} changes")
            
            # Group by file
            by_file = {}
            for change in changes:
                filepath = change['file']
                if filepath not in by_file:
                    by_file[filepath] = []
                by_file[filepath].append(change)
            
            for filepath, file_changes in sorted(by_file.items()):
                print(f"  {filepath}: {len(file_changes)} changes")

def main():
    import sys
    
    # Check if --execute flag is provided
    dry_run = '--execute' not in sys.argv
    
    if dry_run:
        print("DRY RUN MODE - No files will be modified")
        print("Run with --execute flag to apply changes")
        print()
    else:
        print("EXECUTE MODE - Files will be modified!")
        print()
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return
    
    converter = SingleUserConverter(dry_run=dry_run)
    
    # Process route files
    print("\nProcessing route files...")
    converter.process_directory('app/routes')
    
    # Process app/__init__.py separately (needs manual work)
    print("\nNote: app/__init__.py requires manual editing")
    
    # Generate report
    converter.generate_report()
    
    if dry_run:
        print("\n" + "="*80)
        print("DRY RUN COMPLETE - No files were modified")
        print("Review the changes above, then run with --execute to apply")
        print("="*80)

if __name__ == '__main__':
    main()
