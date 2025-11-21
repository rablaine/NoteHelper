"""
Script to make a user an admin.
Run this AFTER logging in for the first time to create your user account.
"""
from app import app, db, User

with app.app_context():
    # Get all users
    users = User.query.all()
    
    if not users:
        print("❌ No users found. Please log in first to create your account.")
    else:
        print(f"Found {len(users)} user(s):")
        for i, user in enumerate(users, 1):
            admin_status = "✅ ADMIN" if user.is_admin else "❌ Not admin"
            print(f"{i}. {user.name} ({user.email}) - {admin_status}")
        
        if len(users) == 1:
            # Only one user, make them admin automatically
            user = users[0]
            if not user.is_admin:
                user.is_admin = True
                db.session.commit()
                print(f"\n✅ Made {user.name} ({user.email}) an admin!")
            else:
                print(f"\n✅ {user.name} is already an admin.")
        else:
            # Multiple users, ask which one
            print("\nEnter the number of the user to make admin:")
            try:
                choice = int(input("> "))
                if 1 <= choice <= len(users):
                    user = users[choice - 1]
                    user.is_admin = True
                    db.session.commit()
                    print(f"\n✅ Made {user.name} ({user.email}) an admin!")
                else:
                    print("❌ Invalid choice.")
            except ValueError:
                print("❌ Invalid input.")
