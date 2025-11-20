from app import db, User, app

with app.app_context():
    user = User.query.get(1)
    if user:
        print(f"User ID: {user.id}")
        print(f"Name: {user.name}")
        print(f"Email: {user.email}")
        print(f"Is Admin: {user.is_admin}")
    else:
        print("User 1 not found")
    
    # Show all users
    print("\nAll users:")
    all_users = User.query.all()
    for u in all_users:
        print(f"  {u.id}: {u.name} ({u.email}) - Admin: {u.is_admin}")
