from app import db, User, Customer, CallLog, Seller, Territory, app

with app.app_context():
    print("=== Data Isolation Test ===\n")
    
    # Count all data by user
    print("Data by User ID:")
    users = User.query.all()
    for user in users:
        print(f"\nUser {user.id}: {user.name}")
        print(f"  Territories: {Territory.query.filter_by(user_id=user.id).count()}")
        print(f"  Sellers: {Seller.query.filter_by(user_id=user.id).count()}")
        print(f"  Customers: {Customer.query.filter_by(user_id=user.id).count()}")
        print(f"  Call Logs: {CallLog.query.filter_by(user_id=user.id).count()}")
    
    # Show that all existing data is linked to user 1
    print(f"\n=== Verification ===")
    print(f"Total territories in DB: {Territory.query.count()}")
    print(f"Territories for user 1: {Territory.query.filter_by(user_id=1).count()}")
    print(f"Territories for other users: {Territory.query.filter(Territory.user_id != 1).count()}")
