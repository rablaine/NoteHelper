"""
Migrate existing seller.territory_id data to the new many-to-many sellers_territories table.
Run this once after applying the database migration.
"""
from app import app, db, Seller, Territory

with app.app_context():
    sellers = Seller.query.all()
    migrated = 0
    
    for seller in sellers:
        if seller.territory_id:
            territory = Territory.query.get(seller.territory_id)
            if territory and not seller.territories.filter_by(id=seller.territory_id).first():
                seller.territories.append(territory)
                migrated += 1
    
    db.session.commit()
    print(f"Migration complete! Migrated {migrated} seller-territory relationships.")
