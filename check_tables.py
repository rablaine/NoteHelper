from app import app, db

with app.app_context():
    # Get all tables
    all_tables = db.session.execute(db.text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).fetchall()
    print("All tables in database:")
    for t in all_tables:
        print(f"  - {t[0]}")
    
    if not all_tables:
        print("\n⚠️  DATABASE IS EMPTY! All tables have been deleted.")
        print("Need to reinitialize with: flask db upgrade")
